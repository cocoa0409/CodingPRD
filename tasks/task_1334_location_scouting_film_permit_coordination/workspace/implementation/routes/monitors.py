"""MonitorAssignment endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int, require_enum,
    make_entity, touch, get_production, get_scoped,
    list_filtered, paginate, get_pagination_params,
    recompute_monitors_confirmed, recompute_compliance,
)

bp = Blueprint("monitors", __name__)


@bp.route("/productions/<pid>/monitor-assignments", methods=["POST"])
def create_monitor_assignment(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["shoot_day_id", "monitor_type", "officer_badge", "hours_booked"])
    sd_id = require_str(payload, "shoot_day_id")
    sd = store.shoot_days.get(sd_id)
    if not sd or sd.get("production_id") != pid:
        raise ApiError(ERR_NOT_FOUND, "ShootDay not found", 404)
    badge = require_str(payload, "officer_badge")
    # One officer may hold at most one non-RELEASED assignment per shoot day
    for ma in store.monitor_assignments.values():
        if (ma.get("shoot_day_id") == sd_id
                and ma.get("officer_badge") == badge
                and ma["status"] != "RELEASED"):
            raise ApiError(ERR_INVALID_REQUEST,
                           "Officer already has a non-released assignment on this day", 400)
    entity = make_entity({
        "production_id": pid,
        "shoot_day_id": sd_id,
        "monitor_type": require_enum(payload, "monitor_type", ["POLICE", "FIRE", "FILM_OFFICER"]),
        "officer_badge": badge,
        "hours_booked": require_int(payload, "hours_booked"),
        "checked_in": False,
        "status": "ASSIGNED",
    })
    store.monitor_assignments[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/monitor-assignments", methods=["GET"])
def list_monitor_assignments(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("shoot_day_id", "status", "monitor_type"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.monitor_assignments, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/monitor-assignments/<rid>/confirm", methods=["POST"])
def confirm_monitor(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    ma = get_scoped(store.monitor_assignments, rid, pid, "MonitorAssignment")
    if ma["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, "MonitorAssignment is not ASSIGNED", 409)
    sd = store.shoot_days.get(ma["shoot_day_id"])
    if not sd or sd["status"] not in ("PLANNED", "READY"):
        raise ApiError(ERR_INVALID_STATE, "ShootDay must be PLANNED or READY to confirm", 409)
    ma["status"] = "CONFIRMED"
    touch(ma)
    recompute_monitors_confirmed(sd)
    touch(sd)
    return success_object(ma)


@bp.route("/productions/<pid>/monitor-assignments/<rid>/release", methods=["POST"])
def release_monitor(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    ma = get_scoped(store.monitor_assignments, rid, pid, "MonitorAssignment")
    if ma["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "MonitorAssignment cannot be released from current state", 409)
    if ma["status"] == "CONFIRMED":
        sd = store.shoot_days.get(ma["shoot_day_id"])
        if sd and sd["status"] == "IN_PROGRESS":
            raise ApiError(ERR_DAY_IN_PROGRESS, "Cannot release CONFIRMED monitor while day is IN_PROGRESS", 409)
    ma["status"] = "RELEASED"
    touch(ma)
    sd = store.shoot_days.get(ma["shoot_day_id"])
    if sd:
        recompute_monitors_confirmed(sd)
        touch(sd)
    return success_object(ma)


@bp.route("/productions/<pid>/monitor-assignments/<rid>/mark-no-show", methods=["POST"])
def mark_no_show(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    ma = get_scoped(store.monitor_assignments, rid, pid, "MonitorAssignment")
    if ma["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "MonitorAssignment must be CONFIRMED to mark no-show", 409)
    ma["status"] = "NO_SHOW"
    touch(ma)
    sd = store.shoot_days.get(ma["shoot_day_id"])
    if sd:
        recompute_monitors_confirmed(sd)
        recompute_compliance(sd)
        # Force VIOLATION if monitors_confirmed < monitors_required
        if sd.get("monitors_confirmed", 0) < sd.get("monitors_required", 0):
            sd["compliance_status"] = "VIOLATION"
        touch(sd)
    return success_object(ma)


@bp.route("/productions/<pid>/monitor-assignments/<rid>/check-in", methods=["POST"])
def check_in_monitor(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    ma = get_scoped(store.monitor_assignments, rid, pid, "MonitorAssignment")
    if ma["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "MonitorAssignment must be CONFIRMED to check in", 409)
    sd = store.shoot_days.get(ma["shoot_day_id"])
    if not sd or sd["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "ShootDay must be IN_PROGRESS for check-in", 409)
    ma["checked_in"] = True
    touch(ma)
    return success_object(ma)
