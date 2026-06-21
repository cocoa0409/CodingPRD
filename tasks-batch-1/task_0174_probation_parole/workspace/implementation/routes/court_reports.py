"""Court-report endpoints (PRD §3.10)."""
from flask import Blueprint, request

import db
from calculations import compliance_rate
from errors import ApiError, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import (
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    recompute_balances,
    require_datetime,
    require_fields,
    sorted_by_created,
)

bp = Blueprint("court_reports", __name__)

REPORT_TYPES = {"PROGRESS", "VIOLATION_SUMMARY", "EARLY_TERMINATION", "REVOCATION"}


@bp.post("/supervisees/<sid>/court-reports")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["report_type", "as_of_date"])
    check_enum(body["report_type"], REPORT_TYPES, "report_type")
    require_datetime(body["as_of_date"], "as_of_date")

    recompute_balances(s)
    cis = [c for c in db.check_ins.values() if c.get("supervisee_id") == sid]
    snapshot = {
        "restitution_balance_cents": s["restitution_balance_cents"],
        "fee_balance_cents": s["fee_balance_cents"],
        "cumulative_violation_points": s["cumulative_violation_points"],
        "supervision_level": s["supervision_level"],
        "compliance_rate": compliance_rate(cis),
    }

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "report_type": body["report_type"],
            "as_of_date": body["as_of_date"],
            "snapshot": snapshot,
            "status": "DRAFT",
        }
    )
    db.court_reports[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/court-reports")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_reports(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [r for r in db.court_reports.values() if r.get("supervisee_id") == sid]
    report_type = request.args.get("report_type")
    if report_type is not None:
        records = [r for r in records if r["report_type"] == report_type]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/court-reports/<rid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_report(sid, rid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.court_reports, rid, sid, label="Court report")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/court-reports/<rid>/file")
@require_roles("Officer", "SupervisingJudge")
def file_report(sid, rid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.court_reports, rid, sid, label="Court report")
    if rec["status"] != "DRAFT":
        raise ApiError(*ERR_INVALID_STATE, "Court report is not DRAFT.")
    rec["status"] = "FILED"
    db.touch(rec)
    return object_response(public(rec), 200)
