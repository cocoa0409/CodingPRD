"""NotificationRecord endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int,
    make_entity, touch, get_production, get_scoped, get_jurisdiction,
    list_filtered, paginate, get_pagination_params, parse_date,
)
from services.calculations import notification_adequacy as calc_adequacy

bp = Blueprint("notifications", __name__)


@bp.route("/productions/<pid>/notifications", methods=["POST"])
def create_notification(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["permit_application_id", "households_reached", "radius_ft_used"])
    pa_id = require_str(payload, "permit_application_id")
    pa = store.permit_applications.get(pa_id)
    if not pa or pa.get("production_id") != pid:
        raise ApiError(ERR_NOT_FOUND, "PermitApplication not found", 404)
    jurisdiction = get_jurisdiction(pa["jurisdiction_id"])
    posted_at = store.clock.now()
    posted_date = posted_at.date() if hasattr(posted_at, 'date') else posted_at
    shoot_start = parse_date(pa["shoot_start_date"])
    cal_days = (shoot_start - posted_date).days
    radius_used = require_int(payload, "radius_ft_used")
    adequate = calc_adequacy(cal_days, radius_used,
                             jurisdiction["notification_lead_calendar_days"],
                             jurisdiction["notification_radius_ft"])
    entity = make_entity({
        "production_id": pid,
        "permit_application_id": pa_id,
        "posted_at": store.clock.now_iso(),
        "households_reached": require_int(payload, "households_reached"),
        "radius_ft_used": radius_used,
        "calendar_days_before_shoot": cal_days,
        "notification_adequate": adequate,
        "status": "POSTED" if adequate else "DEFICIENT",
    })
    store.notification_records[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/notifications", methods=["GET"])
def list_notifications(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("permit_application_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.notification_records, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/notifications/<rid>/acknowledge", methods=["POST"])
def acknowledge_notification(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    n = get_scoped(store.notification_records, rid, pid, "NotificationRecord")
    if n["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, "Notification is not POSTED", 409)
    if not n.get("notification_adequate"):
        raise ApiError(ERR_NOTIFICATION_DEFICIENT, "Notification is not adequate", 422)
    n["status"] = "ACKED"
    touch(n)
    return success_object(n)
