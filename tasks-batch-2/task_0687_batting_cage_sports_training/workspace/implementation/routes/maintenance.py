"""MaintenanceWindow routes (PRD 3.3). Includes the CRITICAL cascade and resolve."""
from flask import Blueprint, request

from clock import clock, parse_iso
from db import db
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND
from helpers import (
    get_json_body,
    require_fields,
    require_enum,
    lookup,
    base_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import maintenance_out
from services.booking_ops import cancel_booking, interval_overlaps_window
from services.derive import (
    recompute_lane,
    recompute_facility,
    recompute_machine,
    machine_on_lane,
    touch,
)

bp = Blueprint("maintenance", __name__)

READ_ROLES = ["FacilityManager", "FrontDesk", "Member", "Instructor"]


@bp.post("/v1/maintenance")
def open_window():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "lane_id", "start_utc", "end_utc", "severity"])
    facility = lookup(db.facilities, body["facility_id"])
    lane = lookup(db.lanes, body["lane_id"])
    if lane["facility_id"] != facility["id"]:
        raise err(ERR_NOT_FOUND, "Lane not in facility scope")
    require_enum(body["severity"], {"ROUTINE", "CRITICAL"}, "severity")

    try:
        start = parse_iso(body["start_utc"])
        end = parse_iso(body["end_utc"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime")
    if end <= start:
        raise err(ERR_INVALID_REQUEST, "end_utc must be after start_utc")

    window = base_common_fields()
    window.update({
        "facility_id": body["facility_id"],
        "lane_id": body["lane_id"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "severity": body["severity"],
        "status": "OPEN",
    })
    db.maintenance[window["id"]] = window

    # Recompute the lane's maint_status from open windows.
    recompute_lane(lane)

    # CRITICAL cascade: cancel overlapping CONFIRMED/CHECKED_IN bookings on this lane.
    if window["severity"] == "CRITICAL":
        for booking in list(db.bookings.values()):
            if booking["status"] not in ("CONFIRMED", "CHECKED_IN"):
                continue
            from services.booking_ops import occupied_lane_ids
            if lane["id"] not in occupied_lane_ids(booking):
                continue
            if interval_overlaps_window(booking, window):
                # Identical refund rules as a normal cancel (PRD 3.3 / 3.7).
                cancel_booking(booking, was_confirmed=True)

    # Recompute facility posture (open_incident_count may have shifted).
    recompute_facility(facility)
    return success(maintenance_out(window), status=201)


@bp.get("/v1/maintenance/<window_id>")
def get_window(window_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    window = lookup(db.maintenance, window_id)
    return success(maintenance_out(window), status=200)


@bp.get("/v1/maintenance")
def list_windows():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    lane_id = request.args.get("lane_id")
    items = [
        w for w in db.maintenance.values()
        if (facility_id is None or w["facility_id"] == facility_id)
        and (lane_id is None or w["lane_id"] == lane_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([maintenance_out(w) for w in page], status=200, pagination=meta)


@bp.post("/v1/maintenance/<window_id>/resolve")
def resolve_window(window_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    window = lookup(db.maintenance, window_id)
    if window["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Window is not OPEN")

    window["status"] = "RESOLVED"
    touch(window)

    lane = db.lanes.get(window["lane_id"])
    if lane is not None:
        recompute_lane(lane)
        # If the last open window on the lane is resolved, reset installed machine.
        remaining_open = [
            w for w in db.maintenance.values()
            if w["lane_id"] == lane["id"] and w["status"] == "OPEN"
        ]
        if not remaining_open:
            machine = machine_on_lane(lane["id"])
            if machine is not None and machine["pitch_count"] != 0:
                machine["pitch_count"] = 0
                touch(machine)
                recompute_machine(machine)
            elif machine is not None:
                recompute_machine(machine)
        facility = db.facilities.get(lane["facility_id"])
        if facility is not None:
            recompute_facility(facility)

    return success(maintenance_out(window), status=200)
