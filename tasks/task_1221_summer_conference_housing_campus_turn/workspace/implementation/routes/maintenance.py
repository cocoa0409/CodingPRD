"""Maintenance windows (PRD 3.10): OCC-guarded creation, conflict and
fall-deadline checks, room out-of-service cascades."""
from datetime import timedelta

from flask import Blueprint, request

from authz import ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR, require_roles
from db import store
from errors import ApiError, date_range_invalid, invalid_state, stale_version
from respond import success
from serialize import ser_maintenance_window
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_int, paginate,
    req_int, req_temporal, sorted_by_creation, touch,
)
from timeutil import as_date

bp = Blueprint("maintenance", __name__)

WORK_ROLES = [FACILITIES, ADMIN]
READ_ROLES = [ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR]


def _inclusive_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.route("/buildings/<bid>/maintenance-windows", methods=["POST"])
def create_window(bid):
    require_roles(WORK_ROLES)
    b = get_or_404(store.buildings, bid)
    data = json_body()
    start = req_temporal(data, "start_date")
    end = req_temporal(data, "end_date")
    buffer_days = opt_int(data, "buffer_days", default=1, minimum=0)
    expected = req_int(data, "expected_building_version")
    if expected != b["version"]:
        raise stale_version("expected_building_version does not match the building's current version")
    start_d = as_date(start)
    end_d = as_date(end)
    if end_d < start_d:
        raise date_range_invalid("end_date must be on or after start_date")
    w = {
        "id": new_id(),
        "_seq": next(store.seq),
        "building_id": bid,
        "start_date": start,
        "end_date": end,
        "buffer_days": buffer_days,
        "blocked_start_date": start_d - timedelta(days=buffer_days),
        "blocked_end_date": end_d + timedelta(days=buffer_days),
        "status": "PLANNED",
    }
    w.update(new_common_fields())
    store.maintenance_windows[w["id"]] = w
    touch(b)
    return success(ser_maintenance_window(w), status=201)


@bp.route("/buildings/<bid>/maintenance-windows", methods=["GET"])
def list_windows(bid):
    require_roles(READ_ROLES)
    get_or_404(store.buildings, bid)
    status = request.args.get("status")
    items = [w for w in store.maintenance_windows.values()
             if w["building_id"] == bid and (status is None or w["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_maintenance_window(w) for w in page], response_type="array", pagination=pagination)


@bp.route("/maintenance-windows/<wid>", methods=["GET"])
def get_window(wid):
    require_roles(READ_ROLES)
    return success(ser_maintenance_window(get_or_404(store.maintenance_windows, wid)))


@bp.route("/maintenance-windows/<wid>/confirm", methods=["POST"])
def confirm_window(wid):
    require_roles(WORK_ROLES)
    w = get_or_404(store.maintenance_windows, wid)
    if w["status"] != "PLANNED":
        raise invalid_state("Window must be PLANNED to confirm")
    b = store.buildings[w["building_id"]]
    if b["status"] not in ("RELEASED", "TURN_ACTIVE", "FALL_PREP"):
        raise invalid_state("Building must be RELEASED, TURN_ACTIVE, or FALL_PREP to confirm a window")
    # Conflict check: occupied nights of RESERVED/CHECKED_IN assignments in
    # the building, and other open windows' blocked intervals.
    for a in store.assignments.values():
        if a["status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        room = store.rooms[a["room_id"]]
        if room["building_id"] != b["id"]:
            continue
        occ_start = as_date(a["checkin_at"])
        occ_end = as_date(a["checkout_at"]) - timedelta(days=1)
        if _inclusive_intersect(occ_start, occ_end, w["blocked_start_date"], w["blocked_end_date"]):
            raise ApiError("ERR_MAINTENANCE_CONFLICT", 409,
                           "Blocked interval intersects occupied nights of a reservation")
    for other in store.maintenance_windows.values():
        if other["id"] == w["id"] or other["building_id"] != b["id"]:
            continue
        if other["status"] in ("CONFIRMED", "IN_PROGRESS") and _inclusive_intersect(
                other["blocked_start_date"], other["blocked_end_date"],
                w["blocked_start_date"], w["blocked_end_date"]):
            raise ApiError("ERR_MAINTENANCE_CONFLICT", 409,
                           "Blocked interval intersects another open maintenance window")
    if not (w["blocked_end_date"] < as_date(b["fall_opening_date"])):
        raise ApiError("ERR_FALL_DEADLINE_IMMINENT", 422,
                       "blocked_end_date must be strictly before fall_opening_date")
    w["status"] = "CONFIRMED"
    touch(w)
    return success(ser_maintenance_window(w))


@bp.route("/maintenance-windows/<wid>/start", methods=["POST"])
def start_window(wid):
    require_roles(WORK_ROLES)
    w = get_or_404(store.maintenance_windows, wid)
    if w["status"] != "CONFIRMED":
        raise invalid_state("Window must be CONFIRMED to start")
    if store.clock.date() < as_date(w["start_date"]):
        raise ApiError("ERR_OUTSIDE_CHECKIN_WINDOW", 422,
                       "Window may start only on or after start_date")
    b = store.buildings[w["building_id"]]
    taken = 0
    for room in store.rooms.values():
        if room["building_id"] == b["id"] and room["status"] in ("RELEASED", "READY"):
            room["status"] = "OUT_OF_SERVICE"
            room["out_of_service_window_id"] = w["id"]
            touch(room)
            taken += 1
    b["out_of_service_room_count"] += taken
    touch(b)
    w["status"] = "IN_PROGRESS"
    touch(w)
    return success(ser_maintenance_window(w))


def _restore_rooms(w):
    b = store.buildings[w["building_id"]]
    restored = 0
    for room in store.rooms.values():
        if room["status"] == "OUT_OF_SERVICE" and room["out_of_service_window_id"] == w["id"]:
            room["status"] = "READY"
            room["out_of_service_window_id"] = None
            touch(room)
            restored += 1
    if restored:
        b["out_of_service_room_count"] -= restored
        touch(b)


@bp.route("/maintenance-windows/<wid>/complete", methods=["POST"])
def complete_window(wid):
    require_roles(WORK_ROLES)
    w = get_or_404(store.maintenance_windows, wid)
    if w["status"] != "IN_PROGRESS":
        raise invalid_state("Window must be IN_PROGRESS to complete")
    _restore_rooms(w)
    w["status"] = "COMPLETED"
    touch(w)
    return success(ser_maintenance_window(w))


@bp.route("/maintenance-windows/<wid>/cancel", methods=["POST"])
def cancel_window(wid):
    require_roles(WORK_ROLES)
    w = get_or_404(store.maintenance_windows, wid)
    if w["status"] not in ("PLANNED", "CONFIRMED"):
        raise invalid_state("Window must be PLANNED or CONFIRMED to cancel")
    _restore_rooms(w)
    w["status"] = "CANCELLED"
    touch(w)
    return success(ser_maintenance_window(w))
