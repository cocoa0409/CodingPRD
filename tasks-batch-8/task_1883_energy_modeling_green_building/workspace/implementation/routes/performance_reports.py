"""PerformanceReport endpoints (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok
from services import (
    GAP_TOLERANCE_PCT,
    check_report_tiling,
    get_project,
    get_report,
    locked_model,
    ser_report,
    stamp,
    touch,
)
from util import (
    VERIFY_OUTCOMES,
    as_dt,
    as_enum,
    as_int,
    as_str,
    body,
    parse_dt,
    pct_round_2dp,
    required,
)

bp = Blueprint("performance_reports", __name__)


@bp.post("/performance-reports")
def create_report():
    _user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    period_start = as_dt(required(data, "period_start"), "period_start")
    period_end = as_dt(required(data, "period_end"), "period_end")
    start_dt = parse_dt(period_start)
    end_dt = parse_dt(period_end)
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_end must be later than period_start"
        )
    actual = as_int(
        required(data, "actual_annual_energy_cost_cents"), "actual_annual_energy_cost_cents"
    )
    if actual <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "actual_annual_energy_cost_cents must be > 0"
        )
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    if project["status"] not in ("CERTIFIED", "PERFORMANCE_REPORTING"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            "Performance reports require a CERTIFIED or PERFORMANCE_REPORTING project",
        )
    proposed = locked_model(project["id"], "PROPOSED")
    if proposed is None:
        raise ApiError(
            "ERR_PROPOSED_MODEL_NOT_LOCKED",
            409,
            "Performance reports are measured against the LOCKED proposed model",
        )
    check_report_tiling(project, start_dt, end_dt)
    gap = pct_round_2dp(
        actual - proposed["annual_energy_cost_confirmed_only_cents"],
        proposed["annual_energy_cost_confirmed_only_cents"],
    )
    within = abs(Decimal(str(gap))) <= GAP_TOLERANCE_PCT
    rec = stamp(
        {
            "project_id": project["id"],
            "period_start": period_start,
            "period_end": period_end,
            "actual_annual_energy_cost_cents": actual,
            "performance_gap_pct": gap,
            "within_tolerance": within,
            "rejection_reason": None,
            "status": "DRAFT",
        }
    )
    DB["performance_reports"][rec["id"]] = rec
    # The first report moves CERTIFIED -> PERFORMANCE_REPORTING automatically.
    if project["status"] == "CERTIFIED":
        project["status"] = "PERFORMANCE_REPORTING"
        touch(project)
    return ok(ser_report(rec), status=201)


@bp.get("/performance-reports/<report_id>")
def get_one_report(report_id):
    auth_headers()
    return ok(ser_report(get_report(report_id)))


@bp.post("/performance-reports/<report_id>/submit")
def submit_report(report_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProjectAdministrator"})
    report = get_report(report_id)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_REPORT_STATE", 409, "submit requires DRAFT")
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(ser_report(report))


@bp.post("/performance-reports/<report_id>/verify")
def verify_report(report_id):
    _user_id, role = auth_headers()
    data = body()
    outcome = as_enum(required(data, "outcome"), VERIFY_OUTCOMES, "outcome")
    rejection_reason = None
    if outcome == "REJECT":
        rejection_reason = as_str(required(data, "rejection_reason"), "rejection_reason")
    require_role(role, {"CertificationReviewer"})
    report = get_report(report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REPORT_STATE", 409, "verify requires SUBMITTED")
    if outcome == "ACCEPT":
        if not report["within_tolerance"]:
            raise ApiError(
                "ERR_PERFORMANCE_GAP_EXCEEDED",
                422,
                "Absolute performance gap exceeds 15.00 percent",
            )
        report["status"] = "ACCEPTED"
    else:
        report["status"] = "REJECTED"
        report["rejection_reason"] = rejection_reason
    touch(report)
    return ok(ser_report(report))


@bp.post("/performance-reports/<report_id>/revise")
def revise_report(report_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProjectAdministrator"})
    report = get_report(report_id)
    if report["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_REPORT_STATE", 409, "revise requires REJECTED")
    report["status"] = "DRAFT"
    report["rejection_reason"] = None
    touch(report)
    return ok(ser_report(report))
