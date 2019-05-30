import steem
import time
import datetime
import copy
import requests
import sys
import traceback
from steem import Steem
from datetime import timedelta

nodes = ['https://anyx.io',
         'https://api.steemit.com',
         'https://rpc.buildteam.io',
         'https://steemd.minnowsupportproject.org']

acc_name = 'steamrebelvapors'     # Replace therising with your steem account name.
s = Steem(nodes, keys=['5JSsu3SWyoG6Ku3SC7oAz8c4eS2fVJnjWAztJqPPB1xoNKL54ZQ', '5Kfs1yV5zvJAjkDih5YSDQQLRiNKW5jfw9AMjT3SSgwKcHaDVZE'], no_broadcast=False)

vote_comments = True

firstrun = True
round_limiting = False     # Set to True if you want to enable round fill limit
trx_list = []
vote_list = []
total = 0
error_count = 0

last_round = []
curr_round = []
next_round = []


def node_failover():
    global nodes, s
    nodes = nodes[1:] + nodes[:1]
    print("Switching to the next node: ", nodes)
    s = Steem(nodes)
    return
    

def get_vote_value(account_name):
    total_vests = float(s.get_account(account_name)['vesting_shares'].split(" ")[0]) + \
                  float(s.get_account(account_name)['received_vesting_shares'].split(" ")[0])
    vests_steem = total_vests*(10**6)*0.02*float(s.get_reward_fund('post')['reward_balance'].split(" ")[0])/float(s.get_reward_fund('post')['recent_claims'])
    vests_sbd = vests_steem*float(s.get_current_median_history_price()['base'].split(" ")[0])/float(s.get_current_median_history_price()['quote'].split(" ")[0])
    return round((vests_sbd/(2*float(requests.get('https://api.coinmarketcap.com/v1/ticker/steem-dollars/').json()[0]['price_usd'])))+(vests_sbd/2), 2)


def convert(amt, curr):
    r1 = requests.get('https://api.coinmarketcap.com/v1/ticker/steem-dollars/')
    r2 = requests.get('https://api.coinmarketcap.com/v1/ticker/steem/')
    tkr1 = r1.json()[0]['price_usd']
    tkr2 = r2.json()[0]['price_usd']
    conv = float(tkr2) / float(tkr1)
    
    print("Converting", amt, curr)
    famt = amt*conv
    fcurr = 'SBD'
    print("Converted to", famt, fcurr)
    
    return famt, fcurr


def refund(bidder, amount, currency, msg):
    global firstrun, error_count
    if (0.01 < amount < 100.0) and (not firstrun):
        memo = 'Refund for invalid bid: ' + msg
        for i in range(16):
            try:
                s.commit.transfer(bidder, amount, currency, memo, acc_name)
                break
            except:
                print("Refund error: ", sys.exc_info()[0])
                print(traceback.format_exc())
                error_count += 1
                if error_count >= 5:
                    node_failover()
                    error_count = 0
                time.sleep(3)
        print(memo)
    elif firstrun:
        print("No refund: First Run")
    else:
        print("No refund: Amount not eligible")
    return


def upvote(votelist, total):
    global last_round, curr_round, next_round, error_count

    last_round = copy.deepcopy(curr_round)
    curr_round = copy.deepcopy(next_round)
    next_round = []
    
    ind = 0
    error_count = 0
    for j in votelist:
        wgt = round(j[0]*100/total, 2)
        link = j[2][j[2].find('@'):]
        while True:
            try:
                s.commit.vote(link, wgt, acc_name)
                break
            except:
                print("Voting error: ", sys.exc_info()[0])
                print(traceback.format_exc())
                error_count += 1
                if error_count >= 5:
                    node_failover()
                    error_count = 0
                time.sleep(4)
            
        last_round[ind]['weight'] = int(wgt*100)
        ind += 1
        time.sleep(5)
        print("Upvoted, weight:", link, wgt)

    # Comment
    for k in votelist:
        wgt = round(k[0]*100/total, 2)
        link = k[2][k[2].find('@'):]
        comment = 'You just rose by {!s}% upvote from @{} courtesy of @{}'.format(wgt, acc_name, k[3])
        while True:
            try:
                s.commit.post(title='', author=acc_name, body=comment, reply_identifier=link)
                break
            except:
                print("Commenting error: ", sys.exc_info()[0])
                print(traceback.format_exc())
                error_count += 1
                if error_count >= 5:
                    node_failover()
                    error_count = 0
                time.sleep(3)
        time.sleep(22)
        print("Upvoted & commented:", link)
        
    return


def validate(bidder, amount, currency, memo):
    global vote_list, curr_round, next_round, total, round_limiting

    # Validation: Min Bid Amt (1.0 SBD)
    if amount < 1.0:
        refund(bidder, amount, currency, 'Min Bid amount is 1 SBD')
        return "Invalid"

    pl = memo[memo.find('@'):]
    perm = pl[pl.find('/')+1:]
    auth = pl[1:pl.find('/')]
    urlapi = memo[memo.find('.com/')+4:]
    memos = [x[2][x[2].find('@'):] for x in vote_list]
    
    d = timedelta(days=3.5)

    # Validation: Round Fill Limit
    if round_limiting:
        try:
            vote_value = get_vote_value(acc_name)
            curr_vote_value = round(0.75 * vote_value * 1.0, 3)
            print("Vote Value: ", curr_vote_value)

            if currency == 'STEEM':
                namt, ncurr = convert(amount, currency)

                if (total + namt) > curr_vote_value:
                    next_round.append({"amount": amount, "currency": currency, "sender": bidder, "author": auth, "permlink": perm, "url": urlapi})
                    return "Invalid"

            if (total + amount) > curr_vote_value:
                print("Total round amt:")
                next_round.append({"amount": amount, "currency": currency, "sender": bidder, "author": auth, "permlink": perm, "url": urlapi})
                return "Invalid"
        except:
            print("Round Limit Error: ", sys.exc_info()[0])
            print(traceback.format_exc())

    # Validation: Valid URL, Post Age, Voted or Not?
    try:
        post = steem.post.Post(pl, s)
                
        votl = [x['voter'] for x in s.get_active_votes(auth, perm)]
        
        if post.is_main_post() or vote_comments:
            if post.time_elapsed() < d:
                if acc_name not in votl:
                    if pl not in memos:
                        curr_round.append({"amount": amount, "currency": currency, "sender": bidder, "author": auth, "permlink": perm, "url": urlapi})
                        return "Valid"
                    else:
                        curr_round[memos.index(pl)]['amount'] += round(amount, 3)
                        if currency == 'STEEM':
                            amount, currency = convert(amount, currency)
                        
                        vote_list[memos.index(pl)][0] += round(amount, 3)
                        total += amount
                        return "Already Present in Votelist"
                else:
                    refund(bidder, amount, currency, 'Post is already upvoted')
                    return "Invalid"
            else:
                refund(bidder, amount, currency, 'Max Post Age exceeded')
                return "Invalid"
        else:
            refund(bidder, amount, currency, 'Invalid URL')
            return "Invalid"
                    
    except:
        refund(bidder, amount, currency, 'Invalid URL')
        print("Validation error: ", sys.exc_info()[0])
        print(traceback.format_exc())
        return "Invalid"


while True:
    try:
        ac = steem.account.Account(acc_name, s)

        prev_time = 0
        for k in ac.get_account_history(-1, 500, filter_by=['vote']):
            if k['voter'] == acc_name:
                prev_time = datetime.datetime.strptime(k['timestamp'], "%Y-%m-%dT%H:%M:%S")
                break
        tt = timedelta(seconds=30+(10000-s.get_account(acc_name)['voting_power'])*43.2)
        print("Current Time: {!s}|Prev vote: {!s}|Next Vote: {!s}".format(datetime.datetime.utcnow(), prev_time, prev_time + tt))

        for i in ac.get_account_history(-1, 500, filter_by=['transfer']):
            if i['trx_id'] in trx_list:
                print("Breaking at Trx_ID: ", i['trx_id'])
                break
            if i['to'] == acc_name:
                bidder = i['from']
                memo = i['memo']
                amount, currency = i['amount'].split(" ")
                amount = float(amount)
                trx_list.append(i['trx_id'])
                print("trx_list after append=", trx_list)
                
                if validate(bidder, amount, currency, memo) == "Valid":
                    if currency == 'STEEM':
                        amount, currency = convert(amount, currency)
                        
                    vote_list.append([round(amount, 3), currency, memo, bidder])
                    total = total + amount
                    print("vote_list , total after append", vote_list, total)
                
        # print ("Votelist: ", votelist, total)
        if (datetime.datetime.utcnow() - prev_time) > tt:
            print("Upvoting: vote_list,total=", vote_list, total)
            upvote(vote_list, total)
            vote_list = []
            total = 0
            trx_list = trx_list[0:5] + trx_list[-5:]
        
        firstrun = False
        time.sleep(10)
    
    except KeyboardInterrupt:
        print("Interrupted")
        break

    except:
        print("Unexpected error: ", sys.exc_info()[0])
        print(traceback.format_exc())
        error_count += 1
        if error_count >= 5:
            node_failover()
            error_count = 0
        time.sleep(10)
