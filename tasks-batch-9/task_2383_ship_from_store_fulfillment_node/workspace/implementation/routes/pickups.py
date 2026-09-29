"""Carrier pickup windows."""
from flask import Blueprint

from constants import (
    API_PREFIX, PICKUP_BUFFER_MINUTES, PICKUP_STATUSES, ROLE_ASSOCIATE, ROLE_CARE,
    ROLE_CARRIER, ROLE_PLANNER,
)
from db import all_of, db, new_row
from errors import ApiError
from middleware import (
    authenticate, body, get_dt, get_int, get_str, pagination_args, query_enum,
    query_str,
)
from routes.common import apply_filter, fetch, finish, listing, show
from util import add_minutes

bp = Blueprint("pickups", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


def _conflicts(store_id, start, end):
    """calculations.carrier_pickup_window_conflict -- pairwise, 30-minute dead-band."""
    for pickup in db.pickups.values():
        if pickup["store_id"] != store_id:
            continue
        if pickup["status"] not in ("SCHEDULED", "CLOSED"):
            continue
        if (start < add_minutes(pickup["window_end_utc"], PICKUP_BUFFER_MINUTES)
                and pickup["window_start_utc"] < add_minutes(end,
                                                             PICKUP_BUFFER_MINUTES)):
            return True
    return False


@bp.route(API_PREFIX + "/stores/<store_id>/carrier-pickups", methods=["POST"])
def create_pickup(store_id):
    authenticate(ROLE_CARRIER, ROLE_PLANNER)
    payload = body()
    carrier_code = get_str(payload, "carrier_code")
    start = get_dt(payload, "window_start_utc")
    end = get_dt(payload, "window_end_utc")
    parcel_capacity = get_int(payload, "parcel_capacity", minimum=1)

    store = fetch("stores", store_id)
    if store["node_status"] not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_STORE_NODE_DEACTIVATED")
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    if _conflicts(store_id, start, end):
        raise ApiError("ERR_PICKUP_WINDOW_OVERLAP")

    pickup = new_row("pickups", {
        "store_id": store_id,
        "carrier_code": carrier_code,
        "window_start_utc": start,
        "window_end_utc": end,
        "parcel_capacity": parcel_capacity,
        "reserved_parcels": 0,
        "status": "SCHEDULED",
    })
    return finish(pickup, 201)


@bp.route(API_PREFIX + "/carrier-pickups", methods=["GET"])
def list_pickups():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("pickups")
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "status", query_enum("status", PICKUP_STATUSES))
    rows = apply_filter(rows, "carrier_code", query_str("carrier_code"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/carrier-pickups/<pickup_id>", methods=["GET"])
def read_pickup(pickup_id):
    authenticate(*ANY_ROLE)
    return show(fetch("pickups", pickup_id))


@bp.route(API_PREFIX + "/carrier-pickups/<pickup_id>/close", methods=["POST"])
def close_pickup(pickup_id):
    authenticate(ROLE_CARRIER)
    pickup = fetch("pickups", pickup_id)
    if pickup["status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    pickup["status"] = "CLOSED"
    return finish(pickup, 200, explicit=[pickup])


@bp.route(API_PREFIX + "/carrier-pickups/<pickup_id>/depart", methods=["POST"])
def depart_pickup(pickup_id):
    authenticate(ROLE_CARRIER)
    pickup = fetch("pickups", pickup_id)
    if pickup["status"] != "CLOSED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    pickup["status"] = "DEPARTED"
    return finish(pickup, 200, explicit=[pickup])


@bp.route(API_PREFIX + "/carrier-pickups/<pickup_id>/cancel", methods=["POST"])
def cancel_pickup(pickup_id):
    authenticate(ROLE_CARRIER)
    pickup = fetch("pickups", pickup_id)
    if pickup["status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    if pickup["reserved_parcels"] != 0:
        raise ApiError("ERR_PICKUP_HAS_PARCELS")
    pickup["status"] = "CANCELLED"
    return finish(pickup, 200, explicit=[pickup])
