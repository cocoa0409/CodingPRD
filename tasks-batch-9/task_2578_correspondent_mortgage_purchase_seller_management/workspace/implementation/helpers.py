"""Shared lookups, roll-up maintenance and cascade helpers."""

from errors import ApiError
from store import (by_created, db, fmt_dt, now, plus_days, public, public_list,
                   touch)
import calc

# --------------------------------------------------------------------------
# path existence (PRD 2.5 group 3, resolved strictly left to right)
# --------------------------------------------------------------------------

def need(collection, rid, error_id):
    record = collection.get(rid)
    if record is None:
        raise ApiError(error_id)
    return record


def need_seller(rid):
    return need(db.sellers, rid, "ERR_SELLER_NOT_FOUND")


def need_product(rid):
    return need(db.products, rid, "ERR_PRODUCT_NOT_FOUND")


def need_statement(rid):
    return need(db.statements, rid, "ERR_STATEMENT_NOT_FOUND")


def need_qc_review(rid):
    return need(db.qc_reviews, rid, "ERR_QC_REVIEW_NOT_FOUND")


def need_commitment(rid):
    return need(db.commitments, rid, "ERR_COMMITMENT_NOT_FOUND")


def need_loan(rid):
    return need(db.loans, rid, "ERR_LOAN_NOT_FOUND")


def need_defect(rid):
    return need(db.defects, rid, "ERR_DEFECT_NOT_FOUND")


def need_condition(rid):
    return need(db.conditions, rid, "ERR_CONDITION_NOT_FOUND")


def need_advice(rid):
    return need(db.advices, rid, "ERR_ADVICE_NOT_FOUND")


def need_demand(rid):
    return need(db.demands, rid, "ERR_DEMAND_NOT_FOUND")


def need_transfer(rid):
    return need(db.transfers, rid, "ERR_TRANSFER_NOT_FOUND")


def need_scorecard(rid):
    return need(db.scorecards, rid, "ERR_SCORECARD_NOT_FOUND")


# --------------------------------------------------------------------------
# child collections
# --------------------------------------------------------------------------

def children(collection, field, value):
    return by_created([r for r in collection.values() if r[field] == value])


def seller_statements(seller_id):
    return children(db.statements, "seller_id", seller_id)


def seller_reviews(seller_id):
    return children(db.qc_reviews, "seller_id", seller_id)


def seller_commitments(seller_id):
    return children(db.commitments, "seller_id", seller_id)


def seller_scorecards(seller_id):
    return children(db.scorecards, "seller_id", seller_id)


def loan_defects(loan_id):
    return children(db.defects, "loan_id", loan_id)


def loan_conditions(loan_id):
    return children(db.conditions, "loan_id", loan_id)


def loan_advices(loan_id):
    return children(db.advices, "loan_id", loan_id)


def loan_demands(loan_id):
    return children(db.demands, "loan_id", loan_id)


def loan_transfers(loan_id):
    return children(db.transfers, "loan_id", loan_id)


# --------------------------------------------------------------------------
# governing-record selectors (PRD 3.2)
# --------------------------------------------------------------------------

def governing_statement(seller_id):
    rows = [s for s in seller_statements(seller_id)
            if s["status"] == "ACCEPTED" and s["audited"] is True]
    if not rows:
        return None
    rows.sort(key=lambda s: (s["fiscal_year_end"], s["_seq"]), reverse=True)
    return rows[0]


def governing_review(seller_id):
    rows = [r for r in seller_reviews(seller_id) if r["status"] == "COMPLETED"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["completed_at"], r["_seq"]), reverse=True)
    return rows[0]


# --------------------------------------------------------------------------
# commitment roll-ups (PRD 2.7)
# --------------------------------------------------------------------------

def recompute_available(commitment):
    commitment["available_amount_cents"] = (
        commitment["notional_amount_cents"]
        - commitment["allocated_amount_cents"]
        - commitment["fulfilled_amount_cents"]
        - commitment["paired_off_amount_cents"]
        - commitment["cancelled_amount_cents"]
    )
    return commitment["available_amount_cents"]


def release_exposure(commitment):
    """A MANDATORY commitment releases its full notional when it goes terminal."""
    if commitment["commitment_type"] != "MANDATORY":
        return
    seller = db.sellers.get(commitment["seller_id"])
    if seller is None:
        return
    seller["open_mandatory_exposure_cents"] -= commitment["notional_amount_cents"]
    if seller["open_mandatory_exposure_cents"] < 0:
        seller["open_mandatory_exposure_cents"] = 0
    touch(seller)


def assess_administrative_flat(commitment, seller):
    """Administrative-flat retirement shared by expiry and cancellation."""
    fee, method = calc.pair_off_fee(commitment, "ADMINISTRATIVE_FLAT")
    commitment["cancelled_amount_cents"] += commitment["available_amount_cents"]
    recompute_available(commitment)
    commitment["pair_off_fee_cents"] = fee
    commitment["pair_off_method"] = method
    seller["fee_receivable_cents"] += fee
    touch(seller)
    release_exposure(commitment)
    touch(commitment)
    return fee


def cancel_open_commitments(seller):
    """Cancel every LOCKED / PARTIALLY_FULFILLED line with no allocation."""
    total = 0
    for commitment in seller_commitments(seller["id"]):
        if commitment["status"] not in ("LOCKED", "PARTIALLY_FULFILLED"):
            continue
        if commitment["allocated_amount_cents"] != 0:
            continue
        commitment["status"] = "CANCELLED"
        total += assess_administrative_flat(commitment, seller)
    return total


# --------------------------------------------------------------------------
# loan review cascades (PRD 3.6)
# --------------------------------------------------------------------------

def on_review_item_added(loan):
    """Conditional cascade fired by a new defect or suspense condition."""
    status = loan["purchase_status"]
    if status == "IN_REVIEW":
        loan["purchase_status"] = "SUSPENDED"
    elif status == "CLEARED_FOR_PURCHASE":
        loan["purchase_status"] = "SUSPENDED"
        for advice in loan_advices(loan["id"]):
            if advice["status"] == "ISSUED":
                advice["status"] = "VOIDED"
                touch(advice)
    touch(loan)


def on_review_item_resolved(loan):
    """Closes the cure cycle when the last open item leaves OPEN."""
    if (loan["purchase_status"] == "SUSPENDED"
            and loan["open_defect_count"] == 0
            and loan["open_suspense_count"] == 0):
        loan["purchase_status"] = "IN_REVIEW"
        loan["review_cycle_count"] += 1
    touch(loan)


# --------------------------------------------------------------------------
# seller standing (PRD 3.2 / 3.9)
# --------------------------------------------------------------------------

def settled_advice(loan_id):
    for advice in loan_advices(loan_id):
        if advice["status"] == "SETTLED":
            return advice
    return None


def datetime_field(record, name, dt):
    record[name] = fmt_dt(dt)
    record["_" + name + "_dt"] = dt


def dt_of(record, name):
    return record.get("_" + name + "_dt")


__all__ = [name for name in dir() if not name.startswith("_")]
