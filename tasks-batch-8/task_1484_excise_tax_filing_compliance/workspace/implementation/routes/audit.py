"""Audit cases: open, request documents, begin review, close."""
from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_enum,
    new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import valid_month_key, month_bucket_index, month_bucket_range
import services

bp = Blueprint("audit", __name__)

AUDIT_FIELDS = ["registration_id", "jurisdiction_id", "period_start", "period_end",
                "records_hold", "assessment_cents", "opened_by_user_id", "status"]

NON_TERMINAL = {"OPENED", "DOCUMENTS_REQUESTED", "UNDER_REVIEW"}


def ser_case(c):
    c["records_hold"] = c["status"] in NON_TERMINAL
    return public(c, AUDIT_FIELDS)


@bp.post("/audit-cases")
def create_case():
    uid, _role = require_roles(["JurisdictionAuditor"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    period_start = req_str(body, "period_start")
    period_end = req_str(body, "period_end")
    if not valid_month_key(period_start) or not valid_month_key(period_end):
        raise_err(errors.ERR_INVALID_REQUEST,
                  "period_start and period_end must be month buckets (YYYY-MM)")
    if month_bucket_index(period_end) < month_bucket_index(period_start):
        raise_err(errors.ERR_INVALID_REQUEST,
                  "period_end precedes period_start")
    get_or_404(DB.registrations, registration_id, "Registration")
    get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    new_buckets = set(month_bucket_range(period_start, period_end))
    for case in DB.audit_cases.values():
        if (case["registration_id"] == registration_id
                and case["jurisdiction_id"] == jurisdiction_id
                and case["status"] in NON_TERMINAL):
            existing = set(month_bucket_range(case["period_start"], case["period_end"]))
            if existing & new_buckets:
                raise_err(errors.ERR_AUDIT_RANGE_OVERLAP,
                          "The range shares a month bucket with a non-terminal audit case")
    case = new_entity({
        "registration_id": registration_id,
        "jurisdiction_id": jurisdiction_id,
        "period_start": period_start,
        "period_end": period_end,
        "records_hold": True,
        "assessment_cents": None,
        "opened_by_user_id": uid,
        "status": "OPENED",
    })
    DB.audit_cases[case["id"]] = case
    return success_object(ser_case(case), 201)


@bp.get("/audit-cases/<aid>")
def get_case(aid):
    require_roles(ALL_READ_ROLES)
    case = get_or_404(DB.audit_cases, aid, "AuditCase")
    return success_object(ser_case(case))


@bp.get("/audit-cases")
def list_cases():
    require_roles(ALL_READ_ROLES)
    items = list(DB.audit_cases.values())
    for param in ("registration_id", "jurisdiction_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    data, limit, offset, total = paginate(items, ser_case)
    return success_list(data, limit, offset, total)


@bp.post("/audit-cases/<aid>/request-documents")
def request_documents(aid):
    require_roles(["JurisdictionAuditor"])
    body_dict(require=False)
    case = get_or_404(DB.audit_cases, aid, "AuditCase")
    if case["status"] != "OPENED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Audit case in status {case['status']} cannot request documents")
    case["status"] = "DOCUMENTS_REQUESTED"
    touch(case)
    return success_object(ser_case(case))


@bp.post("/audit-cases/<aid>/begin-review")
def begin_review(aid):
    require_roles(["JurisdictionAuditor"])
    body_dict(require=False)
    case = get_or_404(DB.audit_cases, aid, "AuditCase")
    if case["status"] not in ("OPENED", "DOCUMENTS_REQUESTED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Audit case in status {case['status']} cannot begin review")
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return success_object(ser_case(case))


@bp.post("/audit-cases/<aid>/close")
def close_case(aid):
    require_roles(["JurisdictionAuditor"])
    body = body_dict()
    outcome = req_enum(body, "outcome", {"NO_CHANGE", "ASSESSMENT"})
    assessment_cents = None
    if outcome == "ASSESSMENT":
        assessment_cents = req_int(body, "assessment_cents", minimum=1)
    case = get_or_404(DB.audit_cases, aid, "AuditCase")
    if case["status"] != "UNDER_REVIEW":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Audit case in status {case['status']} cannot be closed")
    if outcome == "ASSESSMENT":
        case["status"] = "CLOSED_ASSESSMENT"
        case["assessment_cents"] = assessment_cents
    else:
        case["status"] = "CLOSED_NO_CHANGE"
    case["records_hold"] = False
    touch(case)
    return success_object(ser_case(case))
