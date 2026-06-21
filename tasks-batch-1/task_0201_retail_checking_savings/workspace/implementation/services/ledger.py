"""Ledger core: balance derivation, transaction direction, fee tiers, posting.

PRD §3.4 (balances), §3.5 (posting/returning/stopping a debit), §3.6 (fee tiers).
All amounts are integer cents (PRD §2.5); no float, no rounding here.
"""
from db import db, clock_date_iso
from models import stamp_new, touch

# txn_type -> direction (PRD §3.4: direction derived from txn_type, not supplied).
CREDIT_TYPES = {"DEPOSIT", "ACH_CREDIT", "INTEREST"}
DEBIT_TYPES = {"WITHDRAWAL", "ACH_DEBIT", "CHECK_DEBIT", "FEE", "ESCHEAT_SWEEP"}

# Customer-initiated types that refresh last_activity_date and reactivate
# dormant accounts (PRD §3.4, §3.7). System movements (INTEREST/FEE/ESCHEAT_SWEEP)
# do NOT count as activity.
CUSTOMER_ACTIVITY_TYPES = {"DEPOSIT", "WITHDRAWAL", "CHECK_DEBIT", "ACH_DEBIT"}

# Fee tier schedule (PRD §3.6 / SCAFFOLD overdraft_nsf_fee_tier).
TIER1_FEE_CENTS = 3000      # 1st fee-bearing item: $30.00
TIER2_4_FEE_CENTS = 3500    # 2nd-4th items: $35.00 each
DAILY_FEE_ITEM_CAP = 4      # 5th+ item: $0 (daily cap)


def direction_of(txn_type):
    if txn_type in CREDIT_TYPES:
        return "CREDIT"
    return "DEBIT"


def signed_amount(txn):
    """Signed contribution of a POSTED transaction to ledger balance."""
    if txn["direction"] == "CREDIT":
        return txn["amount_cents"]
    return -txn["amount_cents"]


def account_transactions(account_id):
    return [t for t in db.transactions.values() if t["account_id"] == account_id]


def ledger_balance(account_id):
    """Sum of signed amounts of every POSTED transaction (PRD §3.4)."""
    total = 0
    for t in account_transactions(account_id):
        if t["status"] == "POSTED":
            total += signed_amount(t)
    return total


def hold_total(account_id):
    """Sum of amount_cents across PENDING DEBIT transactions (PRD §3.4)."""
    total = 0
    for t in account_transactions(account_id):
        if t["status"] == "PENDING" and t["direction"] == "DEBIT":
            total += t["amount_cents"]
    return total


def available_balance(account_id):
    return ledger_balance(account_id) - hold_total(account_id)


def fees_today(account_id):
    """Count of FeeAssessment rows for the account whose assessed_date == today."""
    today = clock_date_iso()
    return [f for f in db.fee_assessments.values()
            if f["account_id"] == account_id and f["assessed_date"] == today]


def touch_activity(account):
    """Record customer-initiated activity: set last_activity_date to clock date.

    Most-recent customer-initiated POSTED/RETURNED/STOPPED transaction governs
    (PRD §3.4); reactivation likewise sets it to the clock date (PRD §3.7). We
    maintain it as a monotonic stored field updated whenever such activity occurs.
    """
    account["last_activity_date"] = clock_date_iso()


def od_nsf_items_today(account_id):
    return len(fees_today(account_id))


def serialize_account(acct):
    """Project an Account with all computed balance fields (PRD §3.4)."""
    acct["ledger_balance_cents"] = ledger_balance(acct["id"])
    acct["hold_total_cents"] = hold_total(acct["id"])
    acct["available_balance_cents"] = acct["ledger_balance_cents"] - acct["hold_total_cents"]
    acct["od_nsf_items_today"] = od_nsf_items_today(acct["id"])
    return acct


def assess_fee(account_id, source_transaction_id, fee_type):
    """Create a FeeAssessment per the daily tier schedule (PRD §3.6).

    tier_ordinal = 1 + count(fees already recorded today for the account).
    Returns the created FeeAssessment row.
    """
    today = clock_date_iso()
    ordinal = 1 + len(fees_today(account_id))
    if ordinal == 1:
        fee_amount = TIER1_FEE_CENTS
    elif ordinal in (2, 3, 4):
        fee_amount = TIER2_4_FEE_CENTS
    else:
        fee_amount = 0

    fee = {
        "account_id": account_id,
        "source_transaction_id": source_transaction_id,
        "fee_type": fee_type,
        "tier_ordinal": ordinal,
        "fee_amount_cents": fee_amount,
        "assessed_date": today,
    }
    stamp_new(fee)
    db.fee_assessments[fee["id"]] = fee

    # The fee itself is a FEE debit transaction that posts immediately and can
    # push the account further negative; it is never NSF-returned nor recursively
    # fee'd (PRD §3.6). A zero-amount (capped) fee posts a zero-amount txn so the
    # assessment-to-transaction linkage is preserved, but it has no balance effect.
    if fee_amount > 0:
        post_system_txn(account_id, "FEE", fee_amount,
                        ach_origination_id=None)
    return fee


def make_transaction(account_id, txn_type, amount_cents, check_number=None,
                     ach_origination_id=None):
    """Construct a PENDING transaction row (not yet stored)."""
    txn = {
        "account_id": account_id,
        "ach_origination_id": ach_origination_id,
        "txn_type": txn_type,
        "direction": direction_of(txn_type),
        "amount_cents": amount_cents,
        "status": "PENDING",
        "posted_balance_cents": None,
        "check_number": check_number,
        "return_reason_code": None,
    }
    stamp_new(txn)
    return txn


def mark_posted(txn):
    txn["status"] = "POSTED"
    txn["posted_balance_cents"] = ledger_balance(txn["account_id"])
    touch(txn)


def post_system_txn(account_id, txn_type, amount_cents, ach_origination_id=None):
    """Create + immediately POST a system transaction (INTEREST/FEE/ESCHEAT_SWEEP).

    These never run the debit safety gates and never reactivate dormancy.
    """
    txn = make_transaction(account_id, txn_type, amount_cents,
                           ach_origination_id=ach_origination_id)
    db.transactions[txn["id"]] = txn
    mark_posted(txn)
    return txn


def find_matching_stop(account_id, check_number, amount_cents):
    """Return an ACTIVE StopPayment matching check_number with
    max_amount_cents >= amount_cents, else None (PRD §3.5)."""
    if check_number is None:
        return None
    for sp in db.stop_payments.values():
        if (sp["account_id"] == account_id and sp["status"] == "ACTIVE"
                and sp["check_number"] == check_number
                and amount_cents <= sp["max_amount_cents"]):
            return sp
    return None


def floor_for(account):
    """The minimum allowed post-debit available balance (PRD §3.5).

    Courtesy pay is suspended while DORMANT (PRD §3.7); opt-in only applies in
    states where it is honored. The settlement caller passes the account; here
    we honor courtesy pay only when opted in AND not dormant.
    """
    if account["courtesy_pay_opted_in"] and account["status"] != "DORMANT":
        return -account["courtesy_pay_limit_cents"]
    return 0


def settle_debit(account, txn, is_customer_initiated):
    """Run the three debit gates (state, stop-payment, funds) on a PENDING debit.

    Mutates the transaction in place to POSTED / RETURNED / STOPPED, assessing
    fees as needed (PRD §3.5, §3.6). The transaction must already be stored so
    the balance derivation sees it. Returns the txn.
    """
    # Gate 1: account state. A debit against a FROZEN account is RETURNED
    # ACCOUNT_FROZEN. CLOSED/ESCHEATED accounts never reach here for posting.
    if account["status"] == "FROZEN":
        txn["status"] = "RETURNED"
        txn["return_reason_code"] = "ACCOUNT_FROZEN"
        touch(txn)
        return txn

    # Gate 2: stop-payment (only CHECK_DEBIT).
    if txn["txn_type"] == "CHECK_DEBIT":
        sp = find_matching_stop(account["id"], txn["check_number"], txn["amount_cents"])
        if sp is not None:
            txn["status"] = "STOPPED"
            txn["return_reason_code"] = "STOP_PAYMENT"
            touch(txn)
            sp["status"] = "CONSUMED"
            touch(sp)
            return txn

    # Gate 3: funds. Compute post-debit available balance.
    # The PENDING txn currently contributes to hold_total (DEBIT PENDING), so
    # available already nets it out. Post-debit available = current ledger -
    # this debit amount (the hold is replaced by a posted debit of equal size).
    current_ledger = ledger_balance(account["id"])
    post_debit_available = current_ledger - txn["amount_cents"]
    floor = floor_for(account)
    if post_debit_available < floor:
        # NSF return.
        txn["status"] = "RETURNED"
        txn["return_reason_code"] = "NSF"
        touch(txn)
        assess_fee(account["id"], txn["id"], "NSF")
        return txn

    # Posts. Determine whether this is an overdraft post (drives OVERDRAFT fee).
    overdraft = post_debit_available < 0
    mark_posted(txn)
    if overdraft:
        assess_fee(account["id"], txn["id"], "OVERDRAFT")
    return txn
