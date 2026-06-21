"""MaintenanceWindow create + lifecycle (activate/end/cancel)."""
from flask import Blueprint

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body
from services.common import require_str, optional_str, stamp_create, parse_datetime, touch
from services.lookups import get_window, get_service
from services.serializers import window_out
from services import windows as win_svc

bp = Blueprint("windows", __name__)


@bp.route("/maintenance-windows", methods=["POST"])
def create_window():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    service_id = require_str(body, "service_id")
    with db.lock:
        get_service(service_id)  # FK existence (priority 3)
        starts_at = parse_datetime(body, "starts_at")   # shape (priority 4)
        ends_at = parse_datetime(body, "ends_at")
        reason = optional_str(body, "reason")
        # interval well-formedness (priority 5)
        if not (ends_at > starts_at):
            raise ApiError("ERR_INVALID_INTERVAL", "ends_at must be strictly after starts_at.")
        # spacing check (priority 11)
        win_svc.check_spacing(service_id, starts_at, ends_at)
        rec = stamp_create({
            "service_id": service_id,
            "status": "SCHEDULED",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": reason,
        })
        db.windows[rec["id"]] = rec
    return response.success(window_out(rec), 201)


@bp.route("/maintenance-windows/<wid>", methods=["GET"])
def get_one_window(wid):
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin", "IncidentCommander"})
    with db.lock:
        w = get_window(wid)
        return response.success(window_out(w), 200)


@bp.route("/maintenance-windows/<wid>/activate", methods=["POST"])
def activate_window(wid):
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    with db.lock:
        w = get_window(wid)
        if w["status"] != "SCHEDULED":
            raise ApiError("ERR_WINDOW_NOT_SCHEDULED", "Window is not SCHEDULED.")
        now = db.clock.now()
        if not (w["starts_at"] <= now <= w["ends_at"]):
            # PRD 3.8: activation only when current clock is within the closed
            # interval. The state error covers the not-schedulable case;
            # outside the interval is a state-precondition failure.
            raise ApiError("ERR_WINDOW_NOT_SCHEDULED", "Current clock is outside the window interval.")
        w["status"] = "ACTIVE"
        touch(w)
        # CASCADE: suppress TRIGGERED incidents on the service
        win_svc.suppress_triggered_incidents(w["service_id"])
        return response.success(window_out(w), 200)


@bp.route("/maintenance-windows/<wid>/end", methods=["POST"])
def end_window(wid):
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    with db.lock:
        w = get_window(wid)
        if w["status"] != "ACTIVE":
            raise ApiError("ERR_WINDOW_NOT_ACTIVE", "Window is not ACTIVE.")
        w["status"] = "ENDED"
        touch(w)
        return response.success(window_out(w), 200)


@bp.route("/maintenance-windows/<wid>/cancel", methods=["POST"])
def cancel_window(wid):
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    with db.lock:
        w = get_window(wid)
        if w["status"] != "SCHEDULED":
            raise ApiError("ERR_WINDOW_NOT_SCHEDULED", "Window is not SCHEDULED.")
        w["status"] = "CANCELLED"
        touch(w)
        return response.success(window_out(w), 200)
