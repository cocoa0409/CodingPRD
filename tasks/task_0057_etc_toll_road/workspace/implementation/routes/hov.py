from datetime import timedelta
from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, parse_dt, parse_iso, paginate,
                  sorted_by_created)
from serialize import public, public_list

bp = Blueprint("hov", __name__)

BUFFER = timedelta(minutes=15)


@bp.post("/etc/hov-windows")
def create_hov_window():
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    body = get_body()

    # Existence (priority 3): vehicle_id
    vid = body.get("vehicle_id")
    vehicle = None
    if isinstance(vid, str):
        vehicle = db.vehicles.get(vid)
        if vehicle is None:
            raise err(errors.ERR_NOT_FOUND, "Vehicle not found")

    # Ownership (priority 4)
    if role == "AccountHolder" and vehicle is not None and vehicle["account_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of vehicle")

    if vehicle is None:
        require_str(body, "vehicle_id")  # raises ERR_VALIDATION

    window_from = parse_dt(body, "window_from")
    window_to = parse_dt(body, "window_to")

    # HOV overlap with 15-min buffer (priority 10), before occupancy floor (11)
    for w in db.hov_windows.values():
        if w["vehicle_id"] != vehicle["id"] or w["status"] != "DECLARED":
            continue
        ef = parse_iso(w["window_from"])
        et = parse_iso(w["window_to"])
        if _within_buffer(window_from, window_to, ef, et):
            raise err(errors.ERR_HOV_WINDOW_OVERLAP,
                      "HOV window overlaps or is within 15-minute buffer of an existing window")

    # Occupancy floor (priority 11)
    declared = body.get("declared_occupants")
    if isinstance(declared, bool) or not isinstance(declared, int):
        require_int(body, "declared_occupants")  # structural
    if declared < 1:
        raise err(errors.ERR_INVALID_OCCUPANCY, "declared_occupants must be >= 1")

    win = {
        "vehicle_id": vehicle["id"],
        "window_from": body["window_from"],
        "window_to": body["window_to"],
        "declared_occupants": declared,
        "status": "DECLARED",
    }
    init_common(win)
    db.hov_windows[win["id"]] = win
    return success(public(win), status=201)


@bp.get("/etc/hov-windows/<wid>")
def get_hov_window(wid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    w = db.hov_windows.get(wid)
    if w is None:
        raise err(errors.ERR_NOT_FOUND, "HOV window not found")
    if role == "AccountHolder":
        veh = db.vehicles.get(w["vehicle_id"])
        if veh is None or veh["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this window")
    return success(public(w))


@bp.get("/etc/hov-windows")
def list_hov_windows():
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    items = list(db.hov_windows.values())
    vid = request.args.get("vehicle_id")
    if vid is not None:
        items = [w for w in items if w["vehicle_id"] == vid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/etc/hov-windows/<wid>/revoke")
def revoke_hov_window(wid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    w = db.hov_windows.get(wid)
    if w is None:
        raise err(errors.ERR_NOT_FOUND, "HOV window not found")
    if role == "AccountHolder":
        veh = db.vehicles.get(w["vehicle_id"])
        if veh is None or veh["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this window")
    if w["status"] != "DECLARED":
        raise err(errors.ERR_INVALID_STATE, "HOV window is not DECLARED")
    w["status"] = "REVOKED"
    touch(w)
    return success(public(w))


def _within_buffer(a_from, a_to, b_from, b_to):
    """True if [a_from,a_to) overlaps [b_from,b_to) OR the gap between them < 15min."""
    # Expand existing window by buffer on both sides; check overlap.
    eb_from = b_from - BUFFER
    eb_to = b_to + BUFFER
    return a_from < eb_to and eb_from < a_to
