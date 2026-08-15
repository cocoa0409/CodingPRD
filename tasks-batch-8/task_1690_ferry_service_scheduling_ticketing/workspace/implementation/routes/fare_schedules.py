"""FareSchedule endpoints (PRD §3.2). OCC on create (§2.9)."""

from flask import Blueprint, request

from db import db, now_iso, _parse_iso
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SCHEDULE_WINDOW_CONFLICT, ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object
from services.calculations import touch, fuel_surcharge_for_index
from services.fare_schedule import evaluate_fare_transitions, has_live_overlap
from services.serializers import serialize_fare_schedule

bp = Blueprint("fare_schedules", __name__)

ALL_ROLES = ("SchedulerAdmin", "TerminalAgent", "CrewPlanner", "Customer")


@bp.post("/ferry/routes/<route_id>/fare-schedules")
def create_fare_schedule(route_id):
    require_roles("SchedulerAdmin")
    # Priority 3: path id existence
    route = db.routes.get(route_id)
    if route is None:
        raise_error(ERR_NOT_FOUND, "Route not found")

    payload = request.get_json(silent=True) or {}
    eff_from = _parse_iso(payload.get("effective_from"))
    eff_to = _parse_iso(payload.get("effective_to"))

    # Priority 6: window well-formed (effective_from < effective_to)
    if not (eff_from < eff_to):
        raise_error(ERR_SCHEDULE_WINDOW_CONFLICT,
                    "effective_from must be strictly earlier than effective_to")

    # Priority 15: OCC — expected_route_version matches Route.version
    expected = payload.get("expected_route_version")
    if expected is not None and int(expected) != int(route["version"]):
        raise_error(ERR_STALE_VERSION,
                    "expected_route_version does not match current Route.version")

    ts = now_iso()
    fs = {
        "id": db.new_id(),
        "route_id": route_id,
        "season": payload.get("season"),
        "effective_from": payload.get("effective_from"),
        "effective_to": payload.get("effective_to"),
        "passenger_standard_cents": payload.get("passenger_standard_cents"),
        "passenger_resident_cents": payload.get("passenger_resident_cents"),
        "passenger_commuter_cents": payload.get("passenger_commuter_cents"),
        "vehicle_standard_base_cents": payload.get("vehicle_standard_base_cents"),
        "vehicle_oversize_base_cents": payload.get("vehicle_oversize_base_cents"),
        "vehicle_overlength_per_foot_cents": payload.get("vehicle_overlength_per_foot_cents"),
        "fuel_surcharge_cents": payload.get("fuel_surcharge_cents", 0),
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.fare_schedules[fs["id"]] = fs
    # Side effect: increments Route.version by 1 (§3.2)
    touch(route)
    return success_object(serialize_fare_schedule(fs), status=201)


@bp.get("/ferry/fare-schedules/<fs_id>")
def get_fare_schedule(fs_id):
    require_roles(*ALL_ROLES)
    evaluate_fare_transitions()  # lazy evaluation whenever read/consulted (§2.4)
    fs = db.fare_schedules.get(fs_id)
    if fs is None:
        raise_error(ERR_NOT_FOUND, "FareSchedule not found")
    return success_object(serialize_fare_schedule(fs))


def _get_fs(fs_id):
    evaluate_fare_transitions()
    fs = db.fare_schedules.get(fs_id)
    if fs is None:
        raise_error(ERR_NOT_FOUND, "FareSchedule not found")
    return fs


@bp.post("/ferry/fare-schedules/<fs_id>/submit")
def submit_fare_schedule(fs_id):
    require_roles("SchedulerAdmin")
    fs = _get_fs(fs_id)

    # Priority 4: legal state for transition (DRAFT -> SUBMITTED only)
    if fs["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot submit a fare schedule in status {fs['status']}")

    route = db.routes.get(fs["route_id"])
    if route is None or route["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Owning route is not ACTIVE")

    # Priority 6: window well-formed + non-overlapping with live schedules
    eff_from = _parse_iso(fs["effective_from"])
    eff_to = _parse_iso(fs["effective_to"])
    if not (eff_from < eff_to):
        raise_error(ERR_SCHEDULE_WINDOW_CONFLICT,
                    "effective_from must be strictly earlier than effective_to")
    if has_live_overlap(fs["route_id"], fs["season"], eff_from, eff_to,
                        exclude_id=fs["id"]):
        raise_error(ERR_SCHEDULE_WINDOW_CONFLICT,
                    "Overlaps another live fare schedule for the same route and season")

    # fuel_surcharge_determination: surcharge re-pinned at submission (§3.2)
    payload = request.get_json(silent=True) or {}
    fs["fuel_surcharge_cents"] = fuel_surcharge_for_index(
        payload.get("fuel_price_index_cents", 0))
    fs["status"] = "SUBMITTED"
    touch(fs)
    return success_object(serialize_fare_schedule(fs))


@bp.post("/ferry/fare-schedules/<fs_id>/approve")
def approve_fare_schedule(fs_id):
    require_roles("SchedulerAdmin")
    fs = _get_fs(fs_id)
    if fs["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot approve a fare schedule in status {fs['status']}")
    fs["status"] = "APPROVED"
    touch(fs)
    return success_object(serialize_fare_schedule(fs))


@bp.post("/ferry/fare-schedules/<fs_id>/return-for-revision")
def return_for_revision(fs_id):
    require_roles("SchedulerAdmin")
    fs = _get_fs(fs_id)
    if fs["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot return for revision a fare schedule in status {fs['status']}")
    fs["status"] = "DRAFT"
    touch(fs)
    return success_object(serialize_fare_schedule(fs))


@bp.post("/ferry/fare-schedules/<fs_id>/reject")
def reject_fare_schedule(fs_id):
    require_roles("SchedulerAdmin")
    fs = _get_fs(fs_id)
    if fs["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot reject a fare schedule in status {fs['status']}")
    fs["status"] = "REJECTED"
    touch(fs)
    return success_object(serialize_fare_schedule(fs))
