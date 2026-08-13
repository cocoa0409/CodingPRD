"""Audit cases, findings, penalties, debarment."""

from flask import Blueprint, request

import calc
from calc import iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    get_or_404, invalid, ok, ok_list, paginate, opt_str,
                    req_bool, stamp_new, touch)
from services import debar_grower_cascade, ser_audit_case
from store import db

bp = Blueprint("audit", __name__)


def _case(rid):
    return get_or_404(db.audit_cases, rid, "ERR_AUDIT_CASE_NOT_FOUND",
                      "audit case")


@bp.post("/h2a/audit-cases")
@auth("WageAuditor")
def create_audit_case():
    b = body()
    grower_id = b.get("grower_id")
    if grower_id is None:
        raise invalid("grower_id is required")
    get_or_404(db.growers, grower_id, "ERR_GROWER_NOT_FOUND", "grower")
    order_id = b.get("job_order_id")
    order = None
    if order_id is not None:
        order = get_or_404(db.job_orders, order_id, "ERR_JOB_ORDER_NOT_FOUND",
                           "job order")
    if order is not None and order["grower_id"] != grower_id:
        raise ApiError("ERR_GROWER_MISMATCH", 409,
                       "job_order_id belongs to a different grower")
    trigger = b.get("trigger_source")
    if not isinstance(trigger, str) or trigger not in calc.TRIGGER_SOURCE_ENUM:
        raise invalid("trigger_source must be MANUAL, ABANDONMENT, HOUSING, "
                      "or WAGE_DISCREPANCY")
    note = opt_str(b, "note")
    rec = {
        "grower_id": grower_id,
        "job_order_id": order_id,
        "trigger_source": trigger,
        "note": note,
        "opened_on": iso(clock_date()),
        "status": "OPEN",
        "findings": [],
        "provisional_exposure_cents": None,
        "final_penalty_cents": None,
        "debarment_years": None,
        "closed_on": None,
    }
    stamp_new(rec)
    db.audit_cases[rec["id"]] = rec
    return ok(ser_audit_case(rec), 201)


@bp.get("/h2a/audit-cases")
@auth(*ALL_ROLES)
def list_audit_cases():
    q = request.args
    rows = list(db.audit_cases.values())
    for key in ("grower_id", "job_order_id", "status"):
        if q.get(key) is not None:
            rows = [c for c in rows if c[key] == q.get(key)]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_audit_case(c) for c in page], total, limit, offset)


@bp.get("/h2a/audit-cases/<auditCaseId>")
@auth(*ALL_ROLES)
def get_audit_case(auditCaseId):
    return ok(ser_audit_case(_case(auditCaseId)))


def _validate_findings(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise ApiError("ERR_INVALID_FINDINGS", 400,
                       "findings must be a non-empty list")
    cleaned = []
    for f in raw:
        if not isinstance(f, dict):
            raise ApiError("ERR_INVALID_FINDINGS", 400,
                           "each finding must be an object")
        code = f.get("violation_code")
        if not isinstance(code, str) or code not in calc.BASE_PENALTY_CENTS:
            raise ApiError("ERR_INVALID_FINDINGS", 400,
                           "unknown violation_code")
        count = f.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ApiError("ERR_INVALID_FINDINGS", 400,
                           "count must be an integer >= 1")
        willful = f.get("willful")
        if not isinstance(willful, bool):
            raise ApiError("ERR_INVALID_FINDINGS", 400,
                           "willful must be a boolean")
        cleaned.append({"violation_code": code, "count": count,
                        "willful": willful})
    return cleaned


@bp.post("/h2a/audit-cases/<auditCaseId>/issue-findings")
@auth("WageAuditor")
def issue_findings(auditCaseId):
    c = _case(auditCaseId)
    if c["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_CASE_INVALID_STATE", 409,
                       "audit case is not OPEN")
    b = body()
    findings = _validate_findings(b.get("findings"))
    c["findings"] = findings
    c["provisional_exposure_cents"] = calc.provisional_exposure(findings)
    c["status"] = "FINDINGS_ISSUED"
    touch(c)
    return ok(ser_audit_case(c))


@bp.post("/h2a/audit-cases/<auditCaseId>/close-no-action")
@auth("WageAuditor")
def close_no_action(auditCaseId):
    c = _case(auditCaseId)
    if c["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_CASE_INVALID_STATE", 409,
                       "audit case is not FINDINGS_ISSUED")
    c["status"] = "CLOSED_NO_ACTION"
    c["closed_on"] = iso(clock_date())
    touch(c)
    return ok(ser_audit_case(c))


@bp.post("/h2a/audit-cases/<auditCaseId>/assess-penalty")
@auth("WageAuditor")
def assess_penalty(auditCaseId):
    c = _case(auditCaseId)
    if c["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_CASE_INVALID_STATE", 409,
                       "audit case is not FINDINGS_ISSUED")
    b = body()
    good_faith = req_bool(b, "good_faith")
    c["final_penalty_cents"] = calc.final_penalty(c["findings"], good_faith)
    c["status"] = "RESOLVED_PENALTY"
    c["closed_on"] = iso(clock_date())
    touch(c)
    grower = db.growers.get(c["grower_id"])
    if grower is not None and grower["status"] == "ACTIVE":
        grower["status"] = "SUSPENDED"
        touch(grower)
    return ok(ser_audit_case(c))


@bp.post("/h2a/audit-cases/<auditCaseId>/debar")
@auth("WageAuditor")
def debar(auditCaseId):
    c = _case(auditCaseId)
    if c["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_CASE_INVALID_STATE", 409,
                       "audit case is not FINDINGS_ISSUED")
    b = body()
    years = b.get("debarment_years")
    if isinstance(years, bool) or not isinstance(years, int) \
            or years < 1 or years > 3:
        raise ApiError("ERR_INVALID_DEBARMENT_TERM", 400,
                       "debarment_years must be an integer in 1..3")
    c["status"] = "RESOLVED_DEBARMENT"
    c["debarment_years"] = years
    c["closed_on"] = iso(clock_date())
    touch(c)
    grower = db.growers.get(c["grower_id"])
    if grower is not None:
        debar_grower_cascade(grower, years, clock_date())
    return ok(ser_audit_case(c))
