"""Condition report routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_EVENT_NOT_ACTIVE, ERR_EVENT_NOT_FOUND,
                    ERR_REPORT_NOT_FOUND, ERR_STALE_VERSION,
                    ERR_SURFACE_NOT_FOUND, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, parse_iso, to_decimal)
from services.domain import (derive_condition_code,
                             serialize_condition_report,
                             supersede_notams_for_report,
                             recompute_active_notam_count)

bp = Blueprint("condition_reports", __name__)

CONTAMINANT_TYPES = {
    "DRY", "WET", "DRY_SNOW", "WET_SNOW", "COMPACTED_SNOW", "ICE",
    "SLUSH", "STANDING_WATER",
}


@bp.route("/condition-reports", methods=["POST"])
def create_report():
    user_id, role = require_roles("AirfieldInspector")
    body = request.get_json(silent=True) or {}
    required = ("event_id", "surface_id", "contaminant_type", "coverage_pct",
                "depth_inches", "observed_at")
    for f in required:
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if body["contaminant_type"] not in CONTAMINANT_TYPES:
        raise validation("invalid contaminant_type")
    if not is_int(body["coverage_pct"]):
        raise validation("coverage_pct must be an integer")
    if body["coverage_pct"] < 0 or body["coverage_pct"] > 100:
        raise validation("coverage_pct must be 0..100")
    if not is_number(body["depth_inches"]):
        raise validation("depth_inches must be a number")
    depth = to_decimal(body["depth_inches"], "depth_inches")
    if depth < 0:
        raise validation("depth_inches must be >= 0")
    observed_dt = parse_iso(body["observed_at"], "observed_at")
    # logical clock check
    if observed_dt > db.logical_clock:
        raise validation("observed_at must not be ahead of the logical clock")

    # existence: event_id then surface_id
    ev = db.snow_events.get(body["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    surface = db.airfield_surfaces.get(body["surface_id"])
    if not surface:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")

    # state: event must be ACTIVATED or ESCALATED
    if ev["status"] not in ("ACTIVATED", "ESCALATED"):
        raise ApiError(ERR_EVENT_NOT_ACTIVE, 409,
                       "Referenced SnowEvent not ACTIVATED/ESCALATED")

    # OCC check
    if "expected_surface_version" in body:
        esv = body["expected_surface_version"]
        if not is_int(esv):
            raise validation("expected_surface_version must be an integer")
        if esv != surface["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "expected_surface_version mismatch")

    code = derive_condition_code(body["contaminant_type"],
                                 body["coverage_pct"], depth)
    now = now_iso_ms()
    new_id_v = new_id()

    # supersede prior FILED report for same (event_id, surface_id)
    prior = None
    for r in db.condition_reports.values():
        if (r["event_id"] == body["event_id"]
                and r["surface_id"] == body["surface_id"]
                and r["status"] == "FILED"):
            prior = r
            break

    r = {
        "id": new_id_v,
        "event_id": body["event_id"],
        "surface_id": body["surface_id"],
        "contaminant_type": body["contaminant_type"],
        "coverage_pct": body["coverage_pct"],
        "depth_inches": depth,
        "observed_at": body["observed_at"],
        "condition_code": code,
        "status": "FILED",
        "superseded_by_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.condition_reports[r["id"]] = r

    if prior:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = r["id"]
        prior["version"] += 1
        prior["updated_at"] = now
        supersede_notams_for_report(prior["id"])

    surface["current_condition_code"] = code
    surface["version"] += 1
    surface["updated_at"] = now
    recompute_active_notam_count(surface["id"])

    return success_object(serialize_condition_report(r), 201)


@bp.route("/condition-reports", methods=["GET"])
def list_reports():
    user_id, role = require_roles("OpsController", "AirfieldInspector")
    limit, offset = get_pagination(request.args)
    items = list(db.condition_reports.values())
    ev_q = request.args.get("event_id")
    s_q = request.args.get("surface_id")
    st_q = request.args.get("status")
    if ev_q:
        items = [r for r in items if r["event_id"] == ev_q]
    if s_q:
        items = [r for r in items if r["surface_id"] == s_q]
    if st_q:
        items = [r for r in items if r["status"] == st_q]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_condition_report(r) for r in page],
                        limit, offset, total)


@bp.route("/condition-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    user_id, role = require_roles("OpsController", "AirfieldInspector")
    r = db.condition_reports.get(report_id)
    if not r:
        raise not_found(ERR_REPORT_NOT_FOUND, "ConditionReport not found")
    return success_object(serialize_condition_report(r))
