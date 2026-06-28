"""Stall endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from validation import get_body, require_str, require_int

bp = Blueprint("stalls", __name__)


def _check_stall_owner(role, user_id, stall):
    """StallOperator must own the stall (X-User-ID == Stall.id)."""
    if role == "StallOperator" and user_id != stall["id"]:
        raise errors.forbidden()


@bp.route("/stalls", methods=["POST"])
def create_stall():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    body = get_body()
    name = require_str(body, "name")
    timezone = require_str(body, "timezone")
    open_min = require_int(body, "open_minute_of_day")
    close_min = require_int(body, "close_minute_of_day")
    # Field-shape constraints (ERR_INVALID_REQUEST).
    if not (0 <= open_min < 1440):
        raise errors.invalid_request("open_minute_of_day must be in [0, 1440).")
    if not (0 < close_min <= 1440):
        raise errors.invalid_request("close_minute_of_day must be in (0, 1440].")
    if not (open_min < close_min):
        raise errors.invalid_request("open_minute_of_day must be < close_minute_of_day.")
    with store.lock:
        rec = new_entity("Stall", {
            "name": name,
            "timezone": timezone,
            "open_minute_of_day": open_min,
            "close_minute_of_day": close_min,
            "status": "OPEN",
            "equipment_count": 0,
        })
        store.stalls[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/stalls/<sid>", methods=["GET"])
def get_stall(sid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator", "BrandOwner"])
    with store.lock:
        rec = get_or_404(store.stalls, sid)
        return object_response(serialize(rec))


@bp.route("/stalls", methods=["GET"])
def list_stalls():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator", "BrandOwner"])
    with store.lock:
        items, limit, offset, total = paginate(list(store.stalls.values()))
        return array_response(items, limit, offset, total)


@bp.route("/stalls/<sid>/open", methods=["POST"])
def open_stall(sid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.stalls, sid)
        _check_stall_owner(role, user_id, rec)
        if rec["status"] != "CLOSED":
            raise errors.invalid_state()
        rec["status"] = "OPEN"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/stalls/<sid>/close", methods=["POST"])
def close_stall(sid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.stalls, sid)
        _check_stall_owner(role, user_id, rec)
        if rec["status"] != "OPEN":
            raise errors.invalid_state()
        rec["status"] = "CLOSED"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/stalls/<sid>/equipment", methods=["GET"])
def list_stall_equipment(sid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        get_or_404(store.stalls, sid)
        recs = [e for e in store.equipment.values() if e["stall_id"] == sid]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)


@bp.route("/stalls/<sid>/ingredient-lots", methods=["GET"])
def list_stall_lots(sid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        get_or_404(store.stalls, sid)
        recs = [l for l in store.ingredient_lots.values() if l["stall_id"] == sid]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)
