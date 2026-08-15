"""DiversionReport endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_enum, require_dt_field,
    get_program_or_404, get_diversion_report_or_404,
    paginate, sort_created,
)
from services.serializers import diversion_report as serialize_report

bp = Blueprint("diversion", __name__)

READ_ROLES = ("ProgramAdmin", "MunicipalAuditor")
METHODS = ("PROVISIONAL_NET", "FINAL_NET")


def _compute_report(program, period_start, period_end, method):
    """diversion_net_kg calculation (PRD §3.8)."""
    site_ids = {s["id"] for s in db.sites.values() if s["program_id"] == program["id"]}
    window = [
        d for d in db.drops.values()
        if d["site_id"] in site_ids
        and period_start <= d["occurred_at"] < period_end
    ]
    if method == "PROVISIONAL_NET":
        included = [
            d for d in window
            if d["verification_state"] in ("PENDING_AUDIT", "ACCEPTED", "FLAGGED_CONTAMINATED")
        ]
        net = sum(
            float(Decimal(str(d["provisional_net_kg"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            for d in included
        )
    else:
        included = [d for d in window if d["credit_state"] == "FINALLY_CREDITED"]
        net = sum(
            float(Decimal(str(d["final_net_kg"] or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            for d in included
        )
    gross = sum(float(d["gross_weight_kg"]) for d in included)
    contam = sum(float(d["contamination_kg"]) for d in included)
    if gross == 0:
        rate = 0.0
    else:
        rate = float(
            (Decimal(str(net)) / Decimal(str(gross)) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
    return {
        "gross_diverted_kg": db.round_kg(gross),
        "net_diverted_kg": db.round_kg(net),
        "contamination_kg": db.round_kg(contam),
        "diversion_rate_pct": rate,
    }


@bp.route("/programs/<program_id>/diversion-reports", methods=["POST"])
def create_report(program_id):
    user_id, _ = require_roles("MunicipalAuditor")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "period_start", "period_end", "method")
    period_start = require_dt_field(data, "period_start")
    period_end = require_dt_field(data, "period_end")
    method = require_enum(data, "method", METHODS)

    totals = _compute_report(program, period_start, period_end, method)
    report = {
        "id": db.new_id(),
        "program_id": program["id"],
        "period_start": period_start,
        "period_end": period_end,
        "method": method,
        "gross_diverted_kg": totals["gross_diverted_kg"],
        "net_diverted_kg": totals["net_diverted_kg"],
        "contamination_kg": totals["contamination_kg"],
        "diversion_rate_pct": totals["diversion_rate_pct"],
        "certified_by": None,
        "created_by": user_id,
        "status": "DRAFT",
        "created_at": db.iso_now(),
    }
    db.diversion_reports[report["id"]] = report
    return success_object(serialize_report(report), status=201)


@bp.route("/programs/<program_id>/diversion-reports", methods=["GET"])
def list_reports(program_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    items = [r for r in db.diversion_reports.values() if r["program_id"] == program_id]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    if request.args.get("method"):
        items = [r for r in items if r["method"] == request.args["method"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_report(r) for r in page], limit, offset, total)


@bp.route("/programs/<program_id>/diversion-reports/<report_id>", methods=["GET"])
def get_report(program_id, report_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    report = get_diversion_report_or_404(report_id, program_id)
    return success_object(serialize_report(report))


@bp.route("/programs/<program_id>/diversion-reports/<report_id>/certify", methods=["POST"])
def certify_report(program_id, report_id):
    user_id, _ = require_roles("MunicipalAuditor")
    get_program_or_404(program_id)
    report = get_diversion_report_or_404(report_id, program_id)
    if report["status"] != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Report must be DRAFT to certify")
    # Priority 13: segregation of duties
    if report["created_by"] == user_id:
        errors.raise_err(
            errors.ERR_SOD_SAME_USER,
            "DiversionReport certifier must differ from the report's creator",
        )
    if report["period_end"] > db.clock_now():
        errors.raise_err(
            errors.ERR_REPORT_PERIOD_NOT_CLOSED,
            "Cannot certify a report whose period_end is after the current logical clock",
        )
    report["status"] = "CERTIFIED"
    report["certified_by"] = user_id
    # Supersede prior CERTIFIED reports with identical (period, method)
    for other in db.diversion_reports.values():
        if other["id"] == report["id"]:
            continue
        if other["program_id"] != program_id:
            continue
        if other["status"] != "CERTIFIED":
            continue
        if (
            other["period_start"] == report["period_start"]
            and other["period_end"] == report["period_end"]
            and other["method"] == report["method"]
        ):
            other["status"] = "SUPERSEDED"
    return success_object(serialize_report(report))


# --- Flat aliases ---

@bp.route("/diversion-reports", methods=["GET"])
def list_reports_flat():
    require_roles(*READ_ROLES)
    items = list(db.diversion_reports.values())
    if request.args.get("program_id"):
        items = [r for r in items if r["program_id"] == request.args["program_id"]]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    if request.args.get("method"):
        items = [r for r in items if r["method"] == request.args["method"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_report(r) for r in page], limit, offset, total)


@bp.route("/diversion-reports/<report_id>", methods=["GET"])
def get_report_flat(report_id):
    require_roles(*READ_ROLES)
    report = get_diversion_report_or_404(report_id)
    return success_object(serialize_report(report))
