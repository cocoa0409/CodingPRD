"""DispatchOrder routes."""

from flask import Blueprint

from db import DB, new_id
from errors import (
    ERR_BATTERY_NOT_IDLE,
    ERR_INVALID_DISPATCH,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.common import (
    bump_version,
    check_occ,
    get_body,
    get_or_404,
    init_common,
    require_string,
)
from services.time_util import format_iso, server_now


bp = Blueprint("dispatch_orders", __name__, url_prefix="/swap-stations")


@bp.route("/dispatch-orders", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_dispatch_order():
    body = get_body()
    source_station_id = require_string(body, "source_station_id")
    dest_station_id = require_string(body, "dest_station_id")
    battery_id = require_string(body, "battery_id")

    if DB["stations"].get(source_station_id) is None:
        raise_error(ERR_INVALID_INPUT, "source_station_id does not exist")
    if DB["stations"].get(dest_station_id) is None:
        raise_error(ERR_INVALID_INPUT, "dest_station_id does not exist")
    if source_station_id == dest_station_id:
        raise_error(ERR_INVALID_DISPATCH, "source and destination must differ")
    battery = DB["batteries"].get(battery_id)
    if battery is None:
        raise_error(ERR_INVALID_INPUT, "battery_id does not exist")

    if battery.get("status") != "IDLE" or battery.get("station_id") != source_station_id:
        raise_error(ERR_BATTERY_NOT_IDLE,
                    "Battery must be IDLE at source_station_id for dispatch")

    row = {
        "id": new_id(),
        "source_station_id": source_station_id,
        "dest_station_id": dest_station_id,
        "battery_id": battery_id,
        "status": "REQUESTED",
        "dispatched_at": None,
        "delivered_at": None,
    }
    init_common(row)
    DB["dispatch_orders"][row["id"]] = row
    append_audit("DISPATCH_CHANGE", "DispatchOrder", row["id"], None, "REQUESTED")
    return success_response(row, http_status=201)


@bp.route("/dispatch-orders/<order_id>/dispatch", methods=["POST"])
@auth_required(["PlatformAdmin"])
def dispatch(order_id):
    order = get_or_404("dispatch_orders", order_id)
    body = get_body()
    check_occ(order, body)

    if order.get("status") != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Dispatch is not REQUESTED")

    battery = DB["batteries"].get(order["battery_id"])
    if battery is None:
        raise_error(ERR_INVALID_STATE, "Battery missing")
    if battery.get("status") != "IDLE":
        raise_error(ERR_BATTERY_NOT_IDLE, "Battery is not IDLE")

    source_station = DB["stations"].get(order["source_station_id"])

    prev_status = battery["status"]
    battery["status"] = "IN_TRANSIT"
    battery["station_id"] = None
    bump_version(battery)
    append_audit("BATTERY_STATUS_CHANGE", "Battery", battery["id"],
                 prev_status, "IN_TRANSIT")

    if source_station is not None:
        source_station["idle_battery_count"] = max(
            0, int(source_station.get("idle_battery_count", 0)) - 1
        )
        bump_version(source_station)

    prev_order = order["status"]
    order["status"] = "IN_TRANSIT"
    order["dispatched_at"] = format_iso(server_now())
    bump_version(order)
    append_audit("DISPATCH_CHANGE", "DispatchOrder", order_id, prev_order, "IN_TRANSIT")
    return success_response(order)


@bp.route("/dispatch-orders/<order_id>/deliver", methods=["POST"])
@auth_required(["PlatformAdmin"])
def deliver(order_id):
    order = get_or_404("dispatch_orders", order_id)
    body = get_body()
    check_occ(order, body)

    if order.get("status") != "IN_TRANSIT":
        raise_error(ERR_INVALID_STATE, "Dispatch is not IN_TRANSIT")

    battery = DB["batteries"].get(order["battery_id"])
    dest_station = DB["stations"].get(order["dest_station_id"])

    if battery is not None:
        prev_status = battery["status"]
        battery["status"] = "IDLE"
        battery["station_id"] = order["dest_station_id"]
        bump_version(battery)
        append_audit("BATTERY_STATUS_CHANGE", "Battery", battery["id"], prev_status, "IDLE")

    if dest_station is not None:
        dest_station["idle_battery_count"] = int(dest_station.get("idle_battery_count", 0)) + 1
        bump_version(dest_station)

    prev_order = order["status"]
    order["status"] = "DELIVERED"
    order["delivered_at"] = format_iso(server_now())
    bump_version(order)
    append_audit("DISPATCH_CHANGE", "DispatchOrder", order_id, prev_order, "DELIVERED")
    return success_response(order)


@bp.route("/dispatch-orders/<order_id>/cancel", methods=["POST"])
@auth_required(["PlatformAdmin"])
def cancel_dispatch(order_id):
    order = get_or_404("dispatch_orders", order_id)
    body = get_body()
    check_occ(order, body)

    if order.get("status") != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Only REQUESTED dispatch can be cancelled")

    prev = order["status"]
    order["status"] = "CANCELLED"
    bump_version(order)
    append_audit("DISPATCH_CHANGE", "DispatchOrder", order_id, prev, "CANCELLED")
    return success_response(order)
