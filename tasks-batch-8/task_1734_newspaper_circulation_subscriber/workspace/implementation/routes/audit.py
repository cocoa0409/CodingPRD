"""AuditReport endpoints (CirculationDirector only)."""
from flask import Blueprint, request

import domain
from db import _now, bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_audit
from validate import req_date

bp = Blueprint("audit", __name__)


@bp.post("/api/audit-reports")
def create_audit():
    require_roles("CirculationDirector")
    b = body()
    period_start = req_date(b, "period_start")
    period_end = req_date(b, "period_end")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "period_end must be after period_start")
    # Inclusive period overlap against every existing report.
    for a in store.audits.values():
        if period_start <= a["period_end"] and a["period_start"] <= period_end:
            raise ApiError("ERR_AUDIT_PERIOD_OVERLAP", 409,
                           "Audit period overlaps an existing report")
    paid_print, paid_digital, single_copy = domain.audit_totals(period_start, period_end)
    rec = create_rec(store.audits, {
        "period_start": period_start,
        "period_end": period_end,
        "paid_print_subscribers": paid_print,
        "paid_digital_subscribers": paid_digital,
        "single_copy_copies": single_copy,
        "status": "DRAFT",
        "certified_at": None,
    })
    return ok_obj(ser_audit(rec), 201)


@bp.get("/api/audit-reports")
def list_audits():
    require_roles("CirculationDirector")
    recs = by_created(store.audits.values())
    status = request.args.get("status")
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    return paginate(recs, ser_audit)


@bp.get("/api/audit-reports/<aid>")
def get_audit(aid):
    require_roles("CirculationDirector")
    return ok_obj(ser_audit(domain.fetch(store.audits, aid)))


@bp.post("/api/audit-reports/<aid>/certify")
def certify_audit(aid):
    require_roles("CirculationDirector")
    report = domain.fetch(store.audits, aid)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_AUDIT_NOT_DRAFT", 409, "certify requires status DRAFT")
    # Every in-period rack report must be RECONCILED before certification.
    for r in store.rack_reports.values():
        if report["period_start"] <= r["week_start_date"] <= report["period_end"] \
                and r["status"] != "RECONCILED":
            raise ApiError("ERR_UNRECONCILED_RACK_VARIANCE", 409,
                           "An in-period rack sales report is not RECONCILED")
    # Certification recomputes totals; the stale DRAFT snapshot is discarded.
    paid_print, paid_digital, single_copy = domain.audit_totals(
        report["period_start"], report["period_end"])
    report["paid_print_subscribers"] = paid_print
    report["paid_digital_subscribers"] = paid_digital
    report["single_copy_copies"] = single_copy
    report["status"] = "CERTIFIED"
    report["certified_at"] = _now()
    bump(report)
    return ok_obj(ser_audit(report))


@bp.post("/api/audit-reports/<aid>/submit")
def submit_audit(aid):
    require_roles("CirculationDirector")
    report = domain.fetch(store.audits, aid)
    if report["status"] != "CERTIFIED":
        raise ApiError("ERR_AUDIT_NOT_CERTIFIED", 409,
                       "submit requires status CERTIFIED")
    report["status"] = "SUBMITTED"
    bump(report)
    return ok_obj(ser_audit(report))
