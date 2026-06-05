"""MDSReport endpoints (PRD §3.8).

POST /api/mds-reports               — CityRegulator
GET  /api/mds-reports/{id}          — CityRegulator, PlatformAdmin (recompute DRAFT)
POST /api/mds-reports/{id}/finalize — CityRegulator
"""
from flask import Blueprint

import errors
from db import db, stamp_new, touch
from middleware import authenticate, require_role
from response import success
from services.mds import parse_iso, compute_aggregates
from util import get_json_body, require_fields, public

bp = Blueprint("mds_reports", __name__)


@bp.post("/api/mds-reports")
def create_report():
    role, user_id = authenticate()
    require_role(role, {"CityRegulator"})

    body = get_json_body()
    require_fields(body, ["window_start", "window_end"])
    ws = parse_iso(body["window_start"])
    we = parse_iso(body["window_end"])
    if ws is None or we is None:
        raise errors.invalid_request("window_start/window_end must be ISO 8601 instants")
    # Temporal validity (priority 13): window_end strictly after window_start.
    if not (we > ws):
        raise errors.ApiError(
            errors.ERR_INVALID_WINDOW, 422,
            "window_end must be strictly after window_start",
        )

    report = {
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "trip_count": 0,
        "total_billable_minutes": 0,
        "avg_available_vehicles": 0,
        "status": "DRAFT",
    }
    stamp_new(report)
    # Compute initial aggregates (DRAFT).
    report.update(compute_aggregates(report))
    db.mds_reports[report["id"]] = report
    return success(public(report), status=201)


@bp.get("/api/mds-reports/<report_id>")
def get_report(report_id):
    role, user_id = authenticate()
    require_role(role, {"CityRegulator", "PlatformAdmin"})
    report = _require_report(report_id)
    # While DRAFT, recompute live on fetch (PRD §3.8). FINALIZED is frozen.
    if report["status"] == "DRAFT":
        report.update(compute_aggregates(report))
    return success(public(report))


@bp.post("/api/mds-reports/<report_id>/finalize")
def finalize_report(report_id):
    role, user_id = authenticate()
    require_role(role, {"CityRegulator"})
    report = _require_report(report_id)
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Report is not DRAFT")
    # Freeze aggregates at their then-current computed values (PRD §3.8).
    report.update(compute_aggregates(report))
    report["status"] = "FINALIZED"
    touch(report)
    return success(public(report))


def _require_report(report_id):
    report = db.mds_reports.get(report_id)
    if report is None:
        raise errors.not_found("MDS report not found")
    return report
