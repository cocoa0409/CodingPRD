"""Travel expense adjudication (PRD §3.6)."""

from flask import Blueprint

import db
import errors
import validators as v
from errors import fail
from middleware import get_expense, own_expense, roles
from response import ok, paged
from services import calc, lifecycle
from store import public, touch

bp = Blueprint("travel", __name__)


@bp.get("/travel-expenses")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def list_expenses():
    engagement_id = v.query_string("engagement_id")
    status = v.query_string("status")
    rows = []
    for row in db.expenses.values():
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/travel-expenses/<expense_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def read_expense(expense_id):
    return ok(public(get_expense(expense_id)))


@bp.post("/travel-expenses/<expense_id>/approve")
@roles("BookingAgent")
def approve_expense(expense_id):
    expense = get_expense(expense_id)
    own_expense(expense)

    if expense["status"] != "SUBMITTED":
        fail(errors.ERR_TRAVEL_EXPENSE_STATE_INVALID)

    engagement = db.engagements[expense["engagement_id"]]
    if engagement["settlement_status"] != "UNBILLED":
        fail(errors.ERR_TRAVEL_EXPENSE_STATE_INVALID)

    contract = lifecycle.executed_contract(engagement["id"])
    if engagement["booking_status"] != "CONTRACTED" or contract is None:
        fail(errors.ERR_CONTRACT_NOT_EXECUTED)

    speaker = db.speakers[engagement["speaker_id"]]
    amount = calc.travel_reimbursable(
        engagement["is_virtual"],
        contract["travel_policy_code"],
        engagement["travel_allowance_cents"],
        expense["receipts_cents"],
        expense["travel_days"],
        expense["distance_band"],
        speaker["travel_class"],
    )

    expense["status"] = "APPROVED"
    expense["reimbursable_cents"] = amount
    touch(expense)

    engagement["travel_reimbursable_cents"] = \
        engagement["travel_reimbursable_cents"] + amount
    touch(engagement)
    return ok(public(expense))


@bp.post("/travel-expenses/<expense_id>/reject")
@roles("BookingAgent")
def reject_expense(expense_id):
    expense = get_expense(expense_id)
    data = v.body()
    v.opt_string(data, "rejection_reason")
    own_expense(expense)

    if expense["status"] != "SUBMITTED":
        fail(errors.ERR_TRAVEL_EXPENSE_STATE_INVALID)

    expense["status"] = "REJECTED"
    touch(expense)
    return ok(public(expense))
