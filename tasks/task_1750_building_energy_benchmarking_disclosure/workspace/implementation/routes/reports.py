"""Benchmark report endpoints: create, get, list, submit, certify."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import json_object, require_path_entity

bp = Blueprint("reports", __name__)


def _lazy_lapse_recompute(report):
    """PRD 3.5: completeness recomputes lazily on report GET when a consent window
    has newly lapsed. Expiry can only lower completeness, so update only on decrease."""
    building = store.buildings.get(report["building_id"])
    cycle = store.cycles.get(report["cycle_id"])
    if building is None or cycle is None:
        return
    current = core.compute_completeness(building, cycle)
    if core.D(current) < core.D(report["data_completeness_pct"]):
        report["data_completeness_pct"] = current
        db.touch(report)


@bp.post("/v1/benchmark-reports")
def create_report():
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    body = json_object()
    building = None
    if isinstance(body.get("building_id"), str):
        building = store.buildings.get(body["building_id"])
        if building is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced building does not exist")
    if building is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "building_id is required")
    if building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    cycle = None
    if isinstance(body.get("cycle_id"), str):
        cycle = store.cycles.get(body["cycle_id"])
        if cycle is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced cycle does not exist")
    if cycle is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_id is required")
    from validation import validate_schema
    validate_schema(body, {
        "building_id": ("string", True, None),
        "cycle_id": ("string", True, None),
    })
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       "Report creation requires the cycle to be OPEN")
    if core.report_for(building["id"], cycle["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_REPORT", 409,
                       "A BenchmarkReport already exists for this building and cycle")
    if not core.covered(building, cycle):
        raise ApiError("ERR_BUILDING_NOT_COVERED", 422,
                       "Building is not on the covered list for this cycle")
    report = db.new_common({
        "id": db.new_id(),
        "building_id": building["id"],
        "cycle_id": cycle["id"],
        "status": "DRAFT",
        "revision_number": 0,
        "aggregated_kbtu": 0,
        "site_eui": 0.0,
        "data_completeness_pct": 0.0,
        "score_as_reported": None,
        "score_weather_normalized": None,
        "label_grade": None,
        "target_eui": None,
        "submitted_at": None,
        "verified_at": None,
        "verified_site_eui": None,
        "is_late": False,
        "days_late": 0,
    })
    report["aggregated_kbtu"] = core.compute_aggregated_kbtu(building, cycle)
    report["site_eui"] = core.compute_site_eui(report["aggregated_kbtu"], building)
    report["data_completeness_pct"] = core.compute_completeness(building, cycle)
    store.reports[report["id"]] = report
    return created(report)


@bp.get("/v1/benchmark-reports/<report_id>")
def get_report(report_id):
    get_context()
    report = require_path_entity(store.reports, report_id)
    _lazy_lapse_recompute(report)
    return ok(report)


@bp.get("/v1/benchmark-reports")
def list_reports():
    get_context()
    rows = list(store.reports.values())
    for r in rows:
        _lazy_lapse_recompute(r)
    rows = paginate.filter(rows, "building_id")
    rows = paginate.filter(rows, "cycle_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/v1/benchmark-reports/<report_id>/submit")
def submit_report(report_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    report = require_path_entity(store.reports, report_id)
    building = store.buildings.get(report["building_id"])
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this report's building")
    if report["status"] not in ("DRAFT", "FLAGGED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT or FLAGGED report can be submitted")
    cycle = store.cycles.get(report["cycle_id"])
    if cycle["status"] == "SCHEDULED":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "The cycle is not OPEN")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_FILING_CLOSED", 409,
                       "Filing is closed or the cycle is published")
    for f in store.anomaly_flags.values():
        if f["report_id"] == report["id"] and f["status"] == "OPEN":
            raise ApiError("ERR_OPEN_ANOMALIES_EXIST", 409,
                           "The report has anomaly flags with status OPEN")
    # Constraint gate: completeness recomputed at submit time, then threshold.
    # Compute into locals first so a rejected submit leaves no side effects.
    new_agg = core.compute_aggregated_kbtu(building, cycle)
    new_eui = core.compute_site_eui(new_agg, building)
    new_completeness = core.compute_completeness(building, cycle)
    if core.D(new_completeness) < core.D(cycle["data_completeness_min_pct"]):
        raise ApiError("ERR_DATA_COMPLETENESS_BELOW_THRESHOLD", 422,
                       "data_completeness_pct is below the cycle minimum")
    owner = store.owners.get(building["owner_id"])
    if owner is not None and owner["standing"] == "RESTRICTED":
        raise ApiError("ERR_OWNER_RESTRICTED", 403,
                       "Owner standing is RESTRICTED; submissions are blocked")
    report["aggregated_kbtu"] = new_agg
    report["site_eui"] = new_eui
    report["data_completeness_pct"] = new_completeness
    was_flagged = report["status"] == "FLAGGED"
    report["status"] = "SUBMITTED"
    report["submitted_at"] = db.LOGICAL_CLOCK
    if was_flagged:
        report["revision_number"] = report.get("revision_number", 0) + 1
    # Lateness against the effective deadline (approved extension wins).
    deadline = core.effective_deadline(building["id"], cycle)
    days_late = core.whole_days_between(report["submitted_at"], deadline)
    report["days_late"] = days_late
    report["is_late"] = days_late > 0
    if days_late > 0:
        provisional = (min(days_late, cycle["late_fine_cap_days"])
                       * cycle["late_fine_daily_rate_cents"])
        core.create_fine(building["id"], cycle["id"], "LATE_SUBMISSION",
                         provisional, days_late=days_late)
    core.yoy_anomaly_check(report, cycle, building)
    db.touch(report)
    return ok(report)


@bp.post("/v1/benchmark-reports/<report_id>/certify")
def certify_report(report_id):
    uid, _ = get_context()
    require_roles(["ComplianceOfficer"])
    report = require_path_entity(store.reports, report_id)
    if report["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a VERIFIED report can be certified")
    cycle = store.cycles.get(report["cycle_id"])
    if cycle["status"] not in ("OPEN", "FILING_CLOSED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Certification requires the cycle to be OPEN or FILING_CLOSED")
    if uid == cycle["created_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The officer who created the cycle may not certify its reports")
    report["status"] = "CERTIFIED"
    db.touch(report)
    return ok(report)
