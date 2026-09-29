"""Performance windows, notifications and the logical clock."""
from flask import Blueprint

import clock
from constants import (
    API_PREFIX, NOTIFICATION_TYPES, ROLE_ASSOCIATE, ROLE_CARE, ROLE_CARRIER,
    ROLE_PLANNER, WINDOW_STATUSES,
)
from db import all_of
from errors import ApiError
from middleware import (
    authenticate, body, get_dt, pagination_args, query_bool, query_enum, query_int,
    query_str,
)
from response import object_response
from routes.common import apply_filter, fetch, finish_array, listing, show
from services.opsrun import run_operations_close
from util import iso

bp = Blueprint("ops", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


@bp.route(API_PREFIX + "/performance-windows/close", methods=["POST"])
def close_windows():
    authenticate(ROLE_PLANNER)
    marked = []
    closed = run_operations_close(marked)
    return finish_array(closed, explicit=marked)


@bp.route(API_PREFIX + "/performance-windows", methods=["GET"])
def list_windows():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("windows")
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "epoch", query_int("epoch"))
    rows = apply_filter(rows, "status", query_enum("status", WINDOW_STATUSES))
    rows = apply_filter(rows, "breached", query_bool("breached"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/performance-windows/<window_id>", methods=["GET"])
def read_window(window_id):
    authenticate(*ANY_ROLE)
    return show(fetch("windows", window_id))


@bp.route(API_PREFIX + "/notifications", methods=["GET"])
def list_notifications():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("notifications")
    rows = apply_filter(rows, "order_id", query_str("order_id"))
    rows = apply_filter(rows, "assignment_id", query_str("assignment_id"))
    rows = apply_filter(rows, "notification_type",
                        query_enum("notification_type", NOTIFICATION_TYPES))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/notifications/<notification_id>", methods=["GET"])
def read_notification(notification_id):
    authenticate(*ANY_ROLE)
    return show(fetch("notifications", notification_id))


@bp.route(API_PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ROLE_PLANNER)
    payload = body()
    target = get_dt(payload, "to_iso8601")
    previous = clock.now()
    if target < previous:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    clock.set_now(target)
    return object_response({"current_utc": iso(target), "previous_utc": iso(previous)})
