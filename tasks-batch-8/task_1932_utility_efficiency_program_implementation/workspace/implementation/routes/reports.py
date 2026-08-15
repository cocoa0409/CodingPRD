"""Cost-effectiveness report endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("reports", __name__)


@bp.post("/efficiency/reports")
def create_report():
    require_roles({"ProgramManager"})
    body = get_body()
    program = ref_or_404(db.programs, body.get("program_id"), "Program")
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    total_admin_cost_cents = int(body.get("total_admin_cost_cents") or 0)

    fields = core.compute_report_fields(program, period_start, period_end, total_admin_cost_cents)
    report = {
        "program_id": program["id"],
        "period_start": period_start,
        "period_end": period_end,
        "total_incentive_paid_cents": fields["total_incentive_paid_cents"],
        "total_admin_cost_cents": total_admin_cost_cents,
        "total_avoided_kwh": fields["total_avoided_kwh"],
        "trc_ratio": fields["trc_ratio"],
        "trc_flag": fields["trc_flag"],
        "status": "DRAFT",
    }
    db.stamp_new(report)
    db.reports[report["id"]] = report
    return success_object(report, 201)


@bp.get("/efficiency/reports")
def list_reports():
    require_roles({"ProgramManager"})
    items = list(db.reports.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [r for r in items if r.get("program_id") == program_id]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/reports/<report_id>")
def get_report(report_id):
    require_roles({"ProgramManager"})
    return success_object(fetch_or_404(db.reports, report_id, "CostEffectivenessReport"))


@bp.post("/efficiency/reports/<report_id>/finalize")
def finalize_report(report_id):
    require_roles({"ProgramManager"})
    report = fetch_or_404(db.reports, report_id, "CostEffectivenessReport")
    if report["status"] != "DRAFT":
        raise errors.invalid_state(f"Report in {report['status']} cannot be finalized")
    program = db.programs.get(report["program_id"])
    if program is None:
        raise errors.referenced_not_found("Program not found")
    fields = core.compute_report_fields(
        program, report["period_start"], report["period_end"], int(report.get("total_admin_cost_cents") or 0)
    )
    report["total_incentive_paid_cents"] = fields["total_incentive_paid_cents"]
    report["total_avoided_kwh"] = fields["total_avoided_kwh"]
    report["trc_ratio"] = fields["trc_ratio"]
    report["trc_flag"] = fields["trc_flag"]
    report["status"] = "FINAL"
    db.touch(report)
    return success_object(report)
