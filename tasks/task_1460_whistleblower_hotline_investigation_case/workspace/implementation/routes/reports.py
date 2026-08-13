"""Audit committee report endpoints (PRD 3.9): draft snapshot, finalize
(re-compute and freeze), present."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import bump, compute_report_metrics, get_report, paginate, report_view
from util import body, pagination_args, req_dt

bp = Blueprint("reports", __name__)


def _apply_metrics(report):
    metrics = compute_report_metrics(report["period_start"], report["period_end"])
    report.update(metrics)


@bp.post("/hotline/audit-committee-reports")
def create_report():
    user_id, _ = auth(["ComplianceOfficer"])
    data = body()
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    # Half-open window [period_start, period_end): end strictly after start.
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL",
            400,
            "period_end must be strictly later than period_start",
        )
    rec = {
        "id": new_id(),
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "generated_by_id": user_id,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    _apply_metrics(rec)
    DB["reports"][rec["id"]] = rec
    return ok(report_view(rec), status=201)


@bp.get("/hotline/audit-committee-reports")
def list_reports():
    auth(["ComplianceOfficer", "AuditCommitteeMember", "EthicsPlatformAdmin"])
    limit, offset = pagination_args()
    records = list(DB["reports"].values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([report_view(r) for r in page], total, limit, offset)


@bp.post("/hotline/audit-committee-reports/<rid>/finalize")
def finalize_report(rid):
    auth(["ComplianceOfficer"])
    report = get_report(rid)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", 409, "Finalize requires report DRAFT")
    # Metrics re-computed as of finalize, then frozen.
    _apply_metrics(report)
    report["status"] = "FINALIZED"
    bump(report)
    return ok(report_view(report))


@bp.post("/hotline/audit-committee-reports/<rid>/present")
def present_report(rid):
    auth(["AuditCommitteeMember", "ComplianceOfficer"])
    report = get_report(rid)
    if report["status"] != "FINALIZED":
        raise ApiError(
            "ERR_REPORT_NOT_FINALIZED", 409, "Present requires report FINALIZED"
        )
    report["status"] = "PRESENTED"
    bump(report)
    return ok(report_view(report))
