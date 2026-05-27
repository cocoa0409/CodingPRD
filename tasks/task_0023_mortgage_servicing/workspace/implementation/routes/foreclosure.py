"""Foreclosure-case and mediation-session routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_MEDIATION_REQUIRED,
    ERR_NOTICE_PERIOD_VIOLATED,
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
    require_enum,
    require_int,
    require_iso_datetime,
    optional_int,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import (
    get_foreclosure_case,
    get_mediation_session,
    borrower_owns_foreclosure_case,
    borrower_owns_mediation_session,
)

bp = Blueprint("foreclosure", __name__)


def _serialize(o: dict) -> dict:
    return strip_internal(o)


# ---------- GET /foreclosure-cases/{id} ----------
@bp.get("/foreclosure-cases/<cid>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_case(cid: str):
    case = get_foreclosure_case(cid)
    if g.user_role == "Borrower" and not borrower_owns_foreclosure_case(case, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this case.")
    # Refresh cure amount on read
    transitions.refresh_cure_amount(case)
    return response.ok(_serialize(case))


# ---------- POST /foreclosure-cases/{id}/mediation-sessions ----------
@bp.post("/foreclosure-cases/<cid>/mediation-sessions")
@require_auth(roles=["LoanServicer"])
def schedule_session(cid: str):
    case = get_foreclosure_case(cid)
    if case.get("status") != "MEDIATION_REQUIRED":
        raise ApiError(ERR_INVALID_STATE, "Case must be MEDIATION_REQUIRED to schedule a session.")

    body = get_json_body()
    scheduled_for = require_iso_datetime(body, "scheduled_for")

    now = db.utcnow()
    if scheduled_for < now + timedelta(days=calc.MEDIATION_NOTICE_DAYS):
        raise ApiError(ERR_NOTICE_PERIOD_VIOLATED, "scheduled_for must be >= current_utc + 14 days.")

    with db.lock:
        s = new_common_fields()
        s["foreclosure_case_id"] = cid
        s["scheduled_for"] = db.fmt_ts(scheduled_for)
        s["outcome"] = "PENDING"
        s["modification_pi_cents"] = None
        db.mediation_sessions[s["id"]] = s

        case["status"] = "IN_MEDIATION"
        bump(case)
        transitions.refresh_cure_amount(case)

    return response.ok(_serialize(s), status=201)


# ---------- GET /foreclosure-cases/{id}/mediation-sessions ----------
@bp.get("/foreclosure-cases/<cid>/mediation-sessions")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_sessions(cid: str):
    case = get_foreclosure_case(cid)
    if g.user_role == "Borrower" and not borrower_owns_foreclosure_case(case, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this case.")
    limit, offset = parse_pagination()
    items = [s for s in db.mediation_sessions.values() if s.get("foreclosure_case_id") == cid]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /mediation-sessions/{id} ----------
@bp.get("/mediation-sessions/<sid>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_session(sid: str):
    s = get_mediation_session(sid)
    if g.user_role == "Borrower" and not borrower_owns_mediation_session(s, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this session.")
    return response.ok(_serialize(s))


# ---------- POST /mediation-sessions/{id}/record-outcome ----------
@bp.post("/mediation-sessions/<sid>/record-outcome")
@require_auth(roles=["LoanServicer"])
def record_outcome(sid: str):
    s = get_mediation_session(sid)
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"MODIFICATION_AGREED", "FORBEARANCE_AGREED", "NO_AGREEMENT"})
    modification_pi = optional_int(body, "modification_pi_cents")

    case = db.foreclosure_cases.get(s.get("foreclosure_case_id"))
    if case is None or case.get("status") != "IN_MEDIATION":
        raise ApiError(ERR_INVALID_STATE, "Case must be IN_MEDIATION to record an outcome.")
    if s.get("outcome") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Outcome already recorded.")

    if outcome == "MODIFICATION_AGREED":
        if modification_pi is None or modification_pi <= 0:
            from errors import ERR_INVALID_REQUEST
            raise ApiError(ERR_INVALID_REQUEST, "modification_pi_cents required and > 0 for MODIFICATION_AGREED.")

    loan = db.loans.get(case.get("loan_id"))

    with db.lock:
        s["outcome"] = outcome
        if outcome == "MODIFICATION_AGREED":
            s["modification_pi_cents"] = modification_pi
        bump(s)

        if outcome in {"MODIFICATION_AGREED", "FORBEARANCE_AGREED"}:
            case["status"] = "COMPLETED"
            bump(case)
            if outcome == "MODIFICATION_AGREED" and loan is not None:
                loan["scheduled_monthly_pi_cents"] = modification_pi
                transitions.recompute_total_monthly_payment(loan)
                loan["status"] = "REINSTATED"
                bump(loan)
            elif outcome == "FORBEARANCE_AGREED" and loan is not None:
                # Server creates an ACTIVE ForbearancePlan
                now = db.utcnow()
                from datetime import timedelta as _td
                start = now
                end = now + _td(days=180)  # default 6 months
                p = new_common_fields()
                p["loan_id"] = loan["id"]
                p["start_date"] = db.fmt_ts(start)
                p["end_date"] = db.fmt_ts(end)
                p["reduced_payment_cents"] = 0
                p["deferred_total_cents"] = calc.forbearance_deferral(loan, start, end, 0)
                p["status"] = "ACTIVE"
                db.forbearance_plans[p["id"]] = p
                loan["status"] = "FORBEARANCE"
                bump(loan)
        elif outcome == "NO_AGREEMENT":
            case["status"] = "MEDIATION_FAILED"
            bump(case)
            transitions.refresh_cure_amount(case)

    return response.ok(_serialize(s))


# ---------- POST /foreclosure-cases/{id}/schedule-sale ----------
@bp.post("/foreclosure-cases/<cid>/schedule-sale")
@require_auth(roles=["LoanServicer"])
def schedule_sale(cid: str):
    case = get_foreclosure_case(cid)
    body = get_json_body()
    sale_date = require_iso_datetime(body, "sale_date")

    if case.get("status") != "MEDIATION_FAILED":
        raise ApiError(ERR_MEDIATION_REQUIRED, "Case must be MEDIATION_FAILED to schedule sale.")
    now = db.utcnow()
    if sale_date < now + timedelta(days=calc.SALE_NOTICE_DAYS):
        raise ApiError(ERR_MEDIATION_REQUIRED, "sale_date must be >= current_utc + 30 days.")

    with db.lock:
        case["status"] = "SALE_SCHEDULED"
        case["sale_date"] = db.fmt_ts(sale_date)
        bump(case)
        transitions.refresh_cure_amount(case)

    return response.ok(_serialize(case))


# ---------- POST /foreclosure-cases/{id}/withdraw ----------
@bp.post("/foreclosure-cases/<cid>/withdraw")
@require_auth(roles=["LoanServicer"])
def withdraw_case(cid: str):
    case = get_foreclosure_case(cid)
    if case.get("status") not in {"MEDIATION_REQUIRED", "IN_MEDIATION", "MEDIATION_FAILED", "SALE_SCHEDULED"}:
        raise ApiError(ERR_INVALID_STATE, "Case status does not allow withdrawal.")
    loan = db.loans.get(case.get("loan_id"))
    with db.lock:
        case["status"] = "WITHDRAWN"
        bump(case)
        if loan is not None:
            loan["status"] = "REINSTATED"
            bump(loan)
    return response.ok(_serialize(case))
