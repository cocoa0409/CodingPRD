"""The parts return program and the five-hop non-return cascade (PRD 3.7)."""

from flask import Blueprint

import db
import response
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    DEALER_WARRANTY_ADMIN,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
    auth,
    fetch,
)
from routes.common import apply_filters, str_filter
from services import calc, cascade

bp = Blueprint("parts_returns", __name__)

READ_ROLES = (
    WARRANTY_ADMIN,
    CLAIM_ADJUDICATOR,
    ADJUDICATION_MANAGER,
    FIELD_AUDITOR,
    AUDIT_MANAGER,
    DEALER_WARRANTY_ADMIN,
)

ANALYSIS_RESULTS = ("DEFECT_CONFIRMED", "NO_DEFECT_FOUND", "NOT_AVAILABLE")


def dealer_of(row):
    return db.dealers[db.claims[row["claim_id"]]["dealer_id"]]


@bp.get("/warranty/parts-returns/<return_id>")
def read_return(return_id):
    auth(*READ_ROLES)
    row = fetch(db.parts_returns, return_id, "ERR_PARTS_RETURN_NOT_FOUND")
    return response.ok(row)


@bp.get("/warranty/parts-returns")
def list_returns():
    auth(*READ_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.parts_returns)
    rows = apply_filters(
        rows,
        [
            (str_filter("claim_id"), "claim_id"),
            (str_filter("part_id"), "part_id"),
            (str_filter("status"), "status"),
        ],
    )
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/warranty/parts-returns/<return_id>/receive")
def receive_return(return_id):
    auth(WARRANTY_ADMIN)
    row = fetch(db.parts_returns, return_id, "ERR_PARTS_RETURN_NOT_FOUND")
    data = util.body()
    received_date = util.get_date(data, "received_date")
    claim = db.claims[row["claim_id"]]
    if row["status"] not in ("REQUESTED", "NOT_RETURNED"):
        raise ApiError(
            "ERR_PARTS_RETURN_INVALID_STATE",
            "Receipt is admissible only from REQUESTED or NOT_RETURNED.",
        )
    if claim["status"] == "VOID":
        raise ApiError("ERR_PARTS_RETURN_INVALID_STATE", "The linked claim has been voided.")
    dealer = db.dealers[claim["dealer_id"]]
    late = row["status"] == "NOT_RETURNED"
    row["received_date"] = received_date.isoformat()
    row["status"] = "RECEIVED"
    if late:
        reversed_amount = row["debit_amount_cents"]
        row["reversed_amount_cents"] = reversed_amount
        db.touch(row)
        if reversed_amount:
            if claim["payment_status"] == "DEBITED":
                cascade.reinstate_claim(claim, reversed_amount)
            cascade.append_ledger(dealer, "LATE_RETURN_REVERSAL", row["id"], claim["id"], -reversed_amount)
            db.touch(dealer)
    else:
        db.touch(row)
        dealer["open_parts_return_count"] = dealer["open_parts_return_count"] - 1
        db.touch(dealer)
    return response.ok(row)


@bp.post("/warranty/parts-returns/<return_id>/analysis")
def analyze_return(return_id):
    auth(WARRANTY_ADMIN)
    row = fetch(db.parts_returns, return_id, "ERR_PARTS_RETURN_NOT_FOUND")
    data = util.body()
    analysis_result = util.get_enum(data, "analysis_result", ANALYSIS_RESULTS)
    analysis_note = util.get_str(data, "analysis_note")
    if row["status"] != "RECEIVED":
        raise ApiError("ERR_PARTS_RETURN_INVALID_STATE", "Analysis is admissible only from RECEIVED.")
    claim = db.claims[row["claim_id"]]
    dealer = db.dealers[claim["dealer_id"]]
    row["analysis_result"] = analysis_result
    row["analysis_note"] = analysis_note
    row["status"] = "ANALYZED"
    debit = calc.parts_non_return_debit(analysis_result, claim) if claim["status"] == "APPROVED" else 0
    row["debit_amount_cents"] = debit
    db.touch(row)
    if debit > 0:
        cascade.debit_claim(claim, debit)
        cascade.append_ledger(dealer, "PARTS_NO_DEFECT", row["id"], claim["id"], debit)
        db.touch(dealer)
    return response.ok(row)


@bp.post("/warranty/parts-returns/non-return-sweep")
def non_return_sweep():
    auth(WARRANTY_ADMIN)
    clock = db.now()
    swept_count = 0
    debited_claim_ids = []
    total_debit_cents = 0
    touched_dealers = []
    for row in db.ordered(db.parts_returns):
        if row["status"] != "REQUESTED" or clock < row["_due_dt"]:
            continue
        claim = db.claims[row["claim_id"]]
        if claim["status"] != "APPROVED":
            continue
        dealer = db.dealers[claim["dealer_id"]]
        debit = calc.parts_non_return_debit("NOT_RETURNED", claim)
        row["status"] = "NOT_RETURNED"
        row["debit_amount_cents"] = debit
        db.touch(row)
        dealer["open_parts_return_count"] = dealer["open_parts_return_count"] - 1
        cascade.debit_claim(claim, debit)
        if debit:
            cascade.append_ledger(dealer, "PARTS_NON_RETURN", row["id"], claim["id"], debit)
        if dealer["id"] not in [d["id"] for d in touched_dealers]:
            touched_dealers.append(dealer)
        swept_count += 1
        debited_claim_ids.append(claim["id"])
        total_debit_cents += debit
    for dealer in touched_dealers:
        db.touch(dealer)
    return response.raw(
        {
            "swept_count": swept_count,
            "debited_claim_ids": debited_claim_ids,
            "total_debit_cents": total_debit_cents,
        }
    )
