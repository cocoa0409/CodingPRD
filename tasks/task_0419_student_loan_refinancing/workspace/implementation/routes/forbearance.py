"""Forbearance-plan routes: fetch, list, end.

PRD §3.11 (ending forbearance capitalizes accrued interest into principal).
"""
from flask import Blueprint, request

import db
import serialize
from auth import authorize
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from validate import parse_pagination

bp = Blueprint("forbearance", __name__)


@bp.route("/forbearance-plans/<rid>", methods=["GET"])
def get_plan(rid):
    authorize(("GET", "/forbearance-plans/{id}"))
    record = get_or_404(db.forbearance_plans, rid)
    return object_response(serialize.forbearance_plan(record), 200)


@bp.route("/forbearance-plans", methods=["GET"])
def list_plans():
    authorize(("GET", "/forbearance-plans"))
    limit, offset = parse_pagination()
    f_loan = request.args.get("loan_id")
    f_status = request.args.get("status")
    records = list(db.forbearance_plans.values())
    if f_loan is not None:
        records = [r for r in records if r["loan_id"] == f_loan]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.forbearance_plan(r) for r in page], limit, offset, total)


@bp.route("/forbearance-plans/<rid>/end", methods=["POST"])
def end_plan(rid):
    user_id, role = authorize(("POST", "/forbearance-plans/{id}/end"))
    with db.lock():
        plan = get_or_404(db.forbearance_plans, rid)
        loan = get_or_404(db.loans, plan["loan_id"])
        # Defined only when loan is FORBEARANCE and the plan is ACTIVE (PRD §3.11).
        if loan["repayment_status"] != "FORBEARANCE" or plan["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "forbearance end not permitted in current state")
        # Capitalize: fold all accrued interest into principal.
        capitalized = loan["accrued_interest_cents"]
        plan["interest_capitalized_cents"] = capitalized
        loan["principal_balance_cents"] += capitalized
        loan["accrued_interest_cents"] = 0
        plan["status"] = "ENDED"
        db.touch(plan)
        loan["repayment_status"] = "CURRENT"
        db.touch(loan)
        append_audit("LOAN", loan["id"], "LOAN_FORBEARANCE_ENDED", role, user_id)
    return object_response(serialize.forbearance_plan(plan), 200)
