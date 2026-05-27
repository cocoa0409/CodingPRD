"""Forbearance plan routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

import db
import response
from errors import (
    ApiError,
    ERR_FORBEARANCE_WINDOW_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth
from services import calculations as calc
from services import transitions
from services.common import (
    bump,
    new_common_fields,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_iso_datetime,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import (
    get_forbearance_plan,
    get_loan,
    borrower_owns_forbearance_plan,
    borrower_owns_loan,
)

bp = Blueprint("forbearance", __name__)


def _serialize(p: dict) -> dict:
    return strip_internal(p)


# ---------- POST /loans/{id}/forbearance-plans ----------
@bp.post("/loans/<loan_id>/forbearance-plans")
@require_auth(roles=["LoanServicer"])
def propose_plan(loan_id: str):
    loan = get_loan(loan_id)
    body = get_json_body()
    start_date = require_iso_datetime(body, "start_date")
    end_date = require_iso_datetime(body, "end_date")
    reduced_payment_cents = require_int(body, "reduced_payment_cents")

    # Window check: end > start AND (end - start).days <= 360
    if end_date <= start_date:
        raise ApiError(ERR_FORBEARANCE_WINDOW_EXCEEDED, "end_date must be > start_date.")
    if (end_date - start_date).days > calc.MAX_FORBEARANCE_DAYS:
        raise ApiError(ERR_FORBEARANCE_WINDOW_EXCEEDED, "Forbearance window > 12 months.")

    if reduced_payment_cents < 0:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, "reduced_payment_cents must be >= 0.")

    with db.lock:
        p = new_common_fields()
        p["loan_id"] = loan_id
        p["start_date"] = db.fmt_ts(start_date)
        p["end_date"] = db.fmt_ts(end_date)
        p["reduced_payment_cents"] = reduced_payment_cents
        p["deferred_total_cents"] = 0
        p["status"] = "PROPOSED"
        db.forbearance_plans[p["id"]] = p

    return response.ok(_serialize(p), status=201)


# ---------- GET /loans/{id}/forbearance-plans ----------
@bp.get("/loans/<loan_id>/forbearance-plans")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_plans(loan_id: str):
    loan = get_loan(loan_id)
    if g.user_role == "Borrower" and not borrower_owns_loan(loan, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this loan.")
    limit, offset = parse_pagination()
    items = [p for p in db.forbearance_plans.values() if p.get("loan_id") == loan_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /forbearance-plans/{id} ----------
@bp.get("/forbearance-plans/<plan_id>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_plan(plan_id: str):
    p = get_forbearance_plan(plan_id)
    if g.user_role == "Borrower" and not borrower_owns_forbearance_plan(p, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this plan.")
    return response.ok(_serialize(p))


# ---------- POST /forbearance-plans/{id}/activate ----------
@bp.post("/forbearance-plans/<plan_id>/activate")
@require_auth(roles=["LoanServicer"])
def activate_plan(plan_id: str):
    p = get_forbearance_plan(plan_id)
    if p.get("status") != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "ForbearancePlan must be PROPOSED to activate.")
    loan = db.loans.get(p.get("loan_id"))
    if loan is None:
        raise ApiError(ERR_INVALID_STATE, "Plan's loan is missing.")
    if loan.get("status") not in {"DELINQUENT", "FORECLOSURE"}:
        raise ApiError(ERR_INVALID_STATE, "Loan must be DELINQUENT or FORECLOSURE to activate forbearance.")

    with db.lock:
        try:
            start_dt = db.parse_ts(p["start_date"])
            end_dt = db.parse_ts(p["end_date"])
        except Exception:
            from errors import ERR_INVALID_REQUEST
            raise ApiError(ERR_INVALID_REQUEST, "Plan dates corrupt.")
        deferred = calc.forbearance_deferral(loan, start_dt, end_dt, p.get("reduced_payment_cents", 0))
        p["deferred_total_cents"] = deferred
        p["status"] = "ACTIVE"
        bump(p)
        loan["status"] = "FORBEARANCE"
        bump(loan)

    return response.ok(_serialize(p))


# ---------- POST /forbearance-plans/{id}/complete ----------
@bp.post("/forbearance-plans/<plan_id>/complete")
@require_auth(roles=["LoanServicer"])
def complete_plan(plan_id: str):
    p = get_forbearance_plan(plan_id)
    if p.get("status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "ForbearancePlan must be ACTIVE to complete.")
    try:
        end_dt = db.parse_ts(p["end_date"])
    except Exception:
        raise ApiError(ERR_INVALID_STATE, "Plan end_date invalid.")
    now = db.utcnow()
    if now < end_dt:
        raise ApiError(ERR_INVALID_STATE, "Cannot complete forbearance before end_date.")

    loan = db.loans.get(p.get("loan_id"))
    with db.lock:
        p["status"] = "COMPLETED"
        bump(p)
        if loan is not None:
            loan["status"] = "REINSTATED"
            loan["next_due_date"] = db.fmt_ts(now + timedelta(days=30))
            transitions.refresh_dpd(loan)
            bump(loan)

    return response.ok(_serialize(p))


# ---------- POST /forbearance-plans/{id}/terminate ----------
@bp.post("/forbearance-plans/<plan_id>/terminate")
@require_auth(roles=["LoanServicer"])
def terminate_plan(plan_id: str):
    p = get_forbearance_plan(plan_id)
    if p.get("status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "ForbearancePlan must be ACTIVE to terminate.")
    loan = db.loans.get(p.get("loan_id"))
    with db.lock:
        p["status"] = "TERMINATED_EARLY"
        bump(p)
        if loan is not None:
            loan["status"] = "DELINQUENT"
            bump(loan)
    return response.ok(_serialize(p))
