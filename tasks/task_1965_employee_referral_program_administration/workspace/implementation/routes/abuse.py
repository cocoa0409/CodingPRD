"""Abuse cases: manual raise, review, confirm (with FORFEIT cascade), dismiss."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_SOD_VIOLATION)
from middleware import require_role
import services as svc
from services import touch
from util import (req_str, opt_str, check_enum, respond_object, respond_list,
                  parse_pagination, paginate)
from views import abuse_case_view

bp = Blueprint("abuse", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "ComplianceOfficer")


def _get_case(case_id):
    c = store.abuse_cases.get(case_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Abuse case not found")
    return c


@bp.post("/erp/abuse-cases")
def create_case():
    body = request.get_json(silent=True) or {}
    employee_id = req_str(body, "employee_id")
    referral_id = opt_str(body, "referral_id", None)
    case_type = body.get("case_type")
    if not isinstance(case_type, str):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: case_type")
    note = opt_str(body, "note", None)
    check_enum(case_type, svc.CASE_TYPES, "case_type")
    require_role("Recruiter", "TalentAdmin", "ComplianceOfficer")
    if employee_id not in store.employees:
        raise ApiError(ERR_NOT_FOUND, 404, "Employee not found")
    if referral_id is not None and referral_id not in store.referrals:
        raise ApiError(ERR_NOT_FOUND, 404, "Referral not found")
    case = svc.create_abuse_case(employee_id, referral_id, case_type, g.user_id, note)
    return respond_object(abuse_case_view(case), status=201)


@bp.get("/erp/abuse-cases")
def list_cases():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.abuse_cases.values())
    for param in ("employee_id", "referral_id", "status", "case_type"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, total = paginate(items, limit, offset)
    return respond_list([abuse_case_view(c) for c in page], total, limit, offset)


@bp.get("/erp/abuse-cases/<case_id>")
def get_case(case_id):
    require_role(*READ_ROLES)
    return respond_object(abuse_case_view(_get_case(case_id)))


@bp.post("/erp/abuse-cases/<case_id>/start-review")
def start_review(case_id):
    require_role("ComplianceOfficer")
    case = _get_case(case_id)
    if case["status"] in svc.ABUSE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Abuse case is in terminal state %s" % case["status"])
    if case["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN case can move to UNDER_REVIEW (currently %s)" % case["status"])
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return respond_object(abuse_case_view(case))


def _decision_gate(case):
    """State legality, then segregation of duties (decider != raiser)."""
    if case["status"] in svc.ABUSE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Abuse case is in terminal state %s" % case["status"])
    if case["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case cannot be decided from state %s" % case["status"])
    if g.user_id == case["raised_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403,
                       "A compliance officer may not decide a case they raised")


@bp.post("/erp/abuse-cases/<case_id>/confirm")
def confirm_case(case_id):
    body = request.get_json(silent=True) or {}
    resolution_note = opt_str(body, "resolution_note", None)
    require_role("ComplianceOfficer")
    case = _get_case(case_id)
    _decision_gate(case)
    case["status"] = "CONFIRMED"
    case["confirmed_at"] = store.clock
    case["decided_by_user_id"] = g.user_id
    case["resolution_note"] = resolution_note
    touch(case)
    # Cascade: strike + risk recompute (risk is derived at read), then the
    # named referral forfeits if still non-terminal.
    employee = store.employees.get(case["employee_id"])
    if employee is not None:
        employee["fraud_strikes"] += 1
        touch(employee)
    if case["referral_id"]:
        referral = store.referrals.get(case["referral_id"])
        if referral is not None and referral["status"] not in svc.REFERRAL_TERMINAL:
            svc.forfeit_referral_cascade(referral, "system")
    return respond_object(abuse_case_view(case))


@bp.post("/erp/abuse-cases/<case_id>/dismiss")
def dismiss_case(case_id):
    body = request.get_json(silent=True) or {}
    resolution_note = opt_str(body, "resolution_note", None)
    require_role("ComplianceOfficer")
    case = _get_case(case_id)
    _decision_gate(case)
    case["status"] = "DISMISSED"
    case["decided_by_user_id"] = g.user_id
    case["resolution_note"] = resolution_note
    touch(case)
    return respond_object(abuse_case_view(case))
