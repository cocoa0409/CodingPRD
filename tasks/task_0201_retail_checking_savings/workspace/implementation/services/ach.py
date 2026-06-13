"""ACH origination settlement + reversal.

PRD §3.12 (staging), §3.13 (settlement posting order), §3.14 (reversal invariant).
"""
from db import db
from models import touch
from services import ledger
from services.resolve import primary_owner


def legs_of(orig_id):
    return [l for l in db.ach_legs.values() if l["ach_origination_id"] == orig_id]


def ordered_legs(origination):
    """Order legs per posting_order (PRD §3.13).

    CHRONOLOGICAL: all legs ascending by created_at (oldest-first).
    HIGH_TO_LOW:   CREDIT legs first (ascending created_at), then DEBIT legs
                   descending by amount_cents, ties ascending created_at.
    """
    legs = legs_of(origination["id"])
    if origination["posting_order"] == "HIGH_TO_LOW":
        credits = [l for l in legs if l["leg_role"] == "CREDIT"]
        debits = [l for l in legs if l["leg_role"] == "DEBIT"]
        credits.sort(key=lambda l: (l["created_at"], l["_seq"]))
        debits.sort(key=lambda l: (-l["amount_cents"], l["created_at"], l["_seq"]))
        return credits + debits
    # CHRONOLOGICAL (canonical default).
    return sorted(legs, key=lambda l: (l["created_at"], l["_seq"]))


def settle(origination):
    """Post each leg in posting order against the debtor's running balance.

    Mutates legs (produced_transaction_id, settlement_outcome) and the
    origination (totals, version, status). (PRD §3.13)
    """
    debtor = db.accounts.get(origination["debtor_account_id"])
    creditor = db.accounts.get(origination["creditor_account_id"])

    creditor_got_credit = False

    for leg in ordered_legs(origination):
        if leg["leg_role"] == "CREDIT":
            # Credit posts to the creditor account; always posts unless creditor
            # is CLOSED (excluded upstream by the settle precondition).
            txn = ledger.make_transaction(
                creditor["id"], "ACH_CREDIT", leg["amount_cents"],
                ach_origination_id=origination["id"])
            db.transactions[txn["id"]] = txn
            ledger.mark_posted(txn)
            leg["produced_transaction_id"] = txn["id"]
            leg["settlement_outcome"] = "POSTED"
            touch(leg)
            creditor_got_credit = True
        else:
            # Debit hits the debtor account, evaluated against its running
            # available balance (settle_debit reads live balance which includes
            # all prior posted legs in this same settlement).
            txn = ledger.make_transaction(
                debtor["id"], "ACH_DEBIT", leg["amount_cents"],
                ach_origination_id=origination["id"])
            db.transactions[txn["id"]] = txn
            ledger.settle_debit(debtor, txn, is_customer_initiated=False)
            leg["produced_transaction_id"] = txn["id"]
            if txn["status"] == "POSTED":
                leg["settlement_outcome"] = "POSTED"
            else:
                leg["settlement_outcome"] = "RETURNED_NSF"
            touch(leg)

    # Recompute totals from POSTED legs (PRD §3.13).
    _recompute_totals(origination)

    # Credit legs to the creditor refresh last_activity_date (reactivates a
    # dormant creditor) (PRD §3.13, §3.7).
    if creditor_got_credit and creditor is not None:
        ledger.touch_activity(creditor)
        if creditor["status"] == "DORMANT":
            creditor["status"] = "ACTIVE"
        touch(creditor)

    origination["status"] = "SETTLED"
    touch(origination)  # advances version by one


def _recompute_totals(origination):
    total_debit = 0
    total_credit = 0
    for leg in legs_of(origination["id"]):
        if leg["settlement_outcome"] != "POSTED":
            continue
        if leg["leg_role"] == "DEBIT":
            total_debit += leg["amount_cents"]
        else:
            total_credit += leg["amount_cents"]
    origination["total_debit_cents"] = total_debit
    origination["total_credit_cents"] = total_credit


def reverse(origination):
    """Offset every produced transaction and fee (PRD §3.14).

    For each POSTED produced transaction, post an equal-and-opposite POSTED
    transaction. For each FeeAssessment produced by the batch, post an offsetting
    FEE credit transaction. Conserves the two-account ledger total.
    """
    produced_txn_ids = []
    for leg in legs_of(origination["id"]):
        ptid = leg.get("produced_transaction_id")
        if ptid:
            produced_txn_ids.append(ptid)

    for ptid in produced_txn_ids:
        orig_txn = db.transactions.get(ptid)
        if orig_txn is None or orig_txn["status"] != "POSTED":
            continue
        # Equal-and-opposite: a credit reverses a debit and vice versa.
        if orig_txn["direction"] == "CREDIT":
            rev_type = "ACH_DEBIT"
        else:
            rev_type = "ACH_CREDIT"
        rev = ledger.make_transaction(
            orig_txn["account_id"], rev_type, orig_txn["amount_cents"],
            ach_origination_id=origination["id"])
        db.transactions[rev["id"]] = rev
        ledger.mark_posted(rev)

    # Offset every FeeAssessment produced by this batch with a FEE credit.
    batch_fees = _batch_fees(origination["id"], produced_txn_ids)
    for fee in batch_fees:
        if fee["fee_amount_cents"] <= 0:
            continue
        # A FEE credit returns the charged fee. We post an INTEREST-style credit
        # transaction of FEE type that adds back fee_amount_cents.
        rev = ledger.make_transaction(
            fee["account_id"], "FEE", fee["fee_amount_cents"],
            ach_origination_id=origination["id"])
        # Override direction to CREDIT so it adds back the fee.
        rev["direction"] = "CREDIT"
        db.transactions[rev["id"]] = rev
        ledger.mark_posted(rev)

    origination["status"] = "REVERSED"
    touch(origination)  # advances version by one


def _batch_fees(orig_id, produced_txn_ids):
    """FeeAssessments whose source_transaction_id is one of the batch's legs."""
    id_set = set(produced_txn_ids)
    return [f for f in db.fee_assessments.values()
            if f["source_transaction_id"] in id_set]
