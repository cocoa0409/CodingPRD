"""Chargeback / representment cascades (PRD 3.5-3.7, SCAFFOLD state machines)."""

from clock import CLOCK
from db import db
from records import touch
from services.reserve import account_for_merchant, post_entry, recompute_target


def merchant_of(record):
    return db.merchants.get(record["merchant_id"])


def representments_of(chargeback_id):
    return [r for r in db.representments.values() if r["chargeback_id"] == chargeback_id]


def supersede_representment(rep):
    """-> SUPERSEDED; the packet's ATTACHED evidence returns to DRAFT."""
    rep["status"] = "SUPERSEDED"
    touch(rep)
    for item_id in rep["evidence_item_ids"]:
        item = db.evidence_items.get(item_id)
        if item is not None and item["status"] == "ATTACHED":
            item["status"] = "DRAFT"
            touch(item)


def _high_risk_entry(cb, entry_type, source_kind):
    merchant = merchant_of(cb)
    if merchant is not None and merchant["risk_tier"] == "HIGH_RISK":
        acct = account_for_merchant(merchant["id"])
        if acct is not None:
            post_entry(acct, entry_type, cb["amount_cents"], source_kind, cb["id"], None)


def _recompute_and_touch(cb):
    merchant = merchant_of(cb)
    if merchant is not None:
        acct = recompute_target(merchant)
        if acct is not None:
            touch(acct)


def cascade_decided_won(cb, recredited_cents):
    """REPRESENTED -> DECIDED_WON: re-credit, HIGH_RISK holdback release, target recompute."""
    now = CLOCK.now()
    cb["case_status"] = "DECIDED_WON"
    cb["funds_status"] = "FUNDS_RETURNED"
    cb["recredited_cents"] = recredited_cents
    merchant = merchant_of(cb)
    merchant["clearing_balance_cents"] += recredited_cents
    touch(merchant)
    _high_risk_entry(cb, "RELEASE", "CHARGEBACK_WON")
    _recompute_and_touch(cb)
    touch(cb)


def cascade_decided_lost(cb):
    """REPRESENTED/PRE_ARBITRATION -> DECIDED_LOST: debit stands; HIGH_RISK forfeit."""
    cb["case_status"] = "DECIDED_LOST"
    cb["funds_status"] = "DEBIT_FINAL"
    _high_risk_entry(cb, "FORFEIT", "CHARGEBACK_LOST")
    _recompute_and_touch(cb)
    touch(cb)


def cascade_pre_arbitration(cb):
    """DECIDED_WON -> PRE_ARBITRATION: issuer re-debit; HIGH_RISK holdback restored."""
    cb["case_status"] = "PRE_ARBITRATION"
    cb["funds_status"] = "MERCHANT_DEBITED"
    merchant = merchant_of(cb)
    merchant["clearing_balance_cents"] -= cb["recredited_cents"]
    touch(merchant)
    _high_risk_entry(cb, "HOLD", "CHARGEBACK_RECEIPT")
    _recompute_and_touch(cb)
    touch(cb)


def cascade_pre_arb_won(cb):
    """PRE_ARBITRATION -> DECIDED_WON: re-credit recredited_cents; holdback released."""
    cb["case_status"] = "DECIDED_WON"
    cb["funds_status"] = "FUNDS_RETURNED"
    merchant = merchant_of(cb)
    merchant["clearing_balance_cents"] += cb["recredited_cents"]
    touch(merchant)
    _high_risk_entry(cb, "RELEASE", "CHARGEBACK_WON")
    _recompute_and_touch(cb)
    touch(cb)


def cascade_reverse(cb):
    """-> REVERSED: compensating credit, packet supersede, ratio exclusion, holdback release."""
    cb["case_status"] = "REVERSED"
    cb["funds_status"] = "NOT_DEBITED"
    cb["is_ratio_counted"] = False
    merchant = merchant_of(cb)
    merchant["clearing_balance_cents"] += cb["amount_cents"]
    touch(merchant)
    for rep in representments_of(cb["id"]):
        if rep["status"] in ("ASSEMBLED", "SUBMITTED", "RETURNED_FOR_CURE"):
            supersede_representment(rep)
    # The CHARGEBACK_FEE FeeAssessment is NOT auto-waived: network fees survive reversal.
    _high_risk_entry(cb, "RELEASE", "CHARGEBACK_WON")
    _recompute_and_touch(cb)
    touch(cb)


def cascade_expire(cb):
    """-> EXPIRED (clock sweep): debit final; ASSEMBLED packet superseded; target recompute."""
    cb["case_status"] = "EXPIRED"
    cb["funds_status"] = "DEBIT_FINAL"
    for rep in representments_of(cb["id"]):
        if rep["status"] == "ASSEMBLED":
            supersede_representment(rep)
    _recompute_and_touch(cb)
    touch(cb)


def funds_axis_target_recompute(cb):
    """reserve_target trigger: any Chargeback funds_status transition."""
    _recompute_and_touch(cb)
