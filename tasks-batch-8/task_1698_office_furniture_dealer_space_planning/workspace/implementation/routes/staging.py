"""StagingReservation routes: per-day aggregate capacity, receipts with
damaged-goods punch cascade, release and cancel."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE,
    ERR_ORDER_NOT_ACKNOWLEDGED,
    ERR_CAPACITY_EXCEEDED,
    ERR_OVER_RECEIPT,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import (
    get_or_404, new_entity, touch, dealership_of_line, recompute_line_received,
    recompute_install_posture,
)
from util import parse_date
from validate import body_dict, req_str, req_int

bp = Blueprint("staging_reservations", __name__)


def _check_capacity(dealership_id, start_date, end_date, new_units):
    """staging_capacity_utilization: per-day aggregate across RESERVED/OCCUPIED
    reservations of the same dealership; equality with the ceiling is allowed."""
    dealership = db["dealerships"].get(dealership_id)
    if dealership is None:
        return
    capacity = dealership["staging_capacity_units"]
    reservations = [
        r for r in db["staging_reservations"].values()
        if r["status"] in ("RESERVED", "OCCUPIED")
        and _reservation_dealership_id(r) == dealership_id
    ]
    d = start_date
    while d <= end_date:
        occupied = sum(
            r["units"] for r in reservations
            if parse_date(r["start_date"]) <= d <= parse_date(r["end_date"])
        )
        if occupied + new_units > capacity:
            raise_error(ERR_CAPACITY_EXCEEDED,
                        f"staging occupancy on {d.isoformat()} would exceed capacity {capacity}")
        d += timedelta(days=1)


def _reservation_dealership_id(reservation):
    line = db["order_lines"].get(reservation["order_line_id"])
    if line is None:
        return None
    dealership = dealership_of_line(line)
    return dealership["id"] if dealership else None


@bp.route("/api/staging-reservations", methods=["POST"])
def create_reservation():
    authorize(["ProjectManager"])
    body = body_dict()
    order_line_id = req_str(body, "order_line_id")
    # priority 3
    line = get_or_404("order_lines", order_line_id)
    # priority 7d: line ACKNOWLEDGED, or a replacement line still OPEN
    if not (line["status"] == "ACKNOWLEDGED" or (line.get("is_replacement") and line["status"] == "OPEN")):
        raise_error(ERR_ORDER_NOT_ACKNOWLEDGED,
                    f"line is {line['status']}; staging requires an ACKNOWLEDGED line (or an OPEN replacement line)")
    # priority 8a
    units = req_int(body, "units", minv=1)
    start_s = req_str(body, "start_date")
    end_s = req_str(body, "end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    if start_d is None or end_d is None:
        raise_error(ERR_INVALID_REQUEST, "start_date / end_date must be YYYY-MM-DD dates")
    # priority 8b: window ordering (inclusive bounds)
    if end_d < start_d:
        raise_error(ERR_INVALID_DATE_RANGE, "end_date must be on or after start_date")
    # priority 8e: per-day aggregate capacity
    dealership = dealership_of_line(line)
    if dealership is not None:
        _check_capacity(dealership["id"], start_d, end_d, units)
    reservation = new_entity("staging_reservations", {
        "order_line_id": order_line_id,
        "units": units,
        "start_date": start_s,
        "end_date": end_s,
        "received_units": 0,
        "status": "RESERVED",
    })
    return success_object(public(reservation), status=201)


@bp.route("/api/staging-reservations", methods=["GET"])
def list_reservations():
    authorize(ALL_ROLES)
    return list_response("staging_reservations", ["order_line_id", "status"])


@bp.route("/api/staging-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    authorize(ALL_ROLES)
    return get_response("staging_reservations", reservation_id)


@bp.route("/api/staging-reservations/<reservation_id>/receive", methods=["POST"])
def receive_reservation(reservation_id):
    authorize(["WarehouseLead"])
    reservation = get_or_404("staging_reservations", reservation_id)
    # priority 4: receive acts on a RESERVED reservation
    if reservation["status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, f"cannot receive against a reservation in status {reservation['status']}")
    body = body_dict()
    received = body.get("received_units")
    if received is None or not isinstance(received, int) or isinstance(received, bool):
        raise_error(ERR_INVALID_REQUEST, "received_units is required and must be an integer")
    condition = body.get("condition")
    if not isinstance(condition, str) or not condition.strip():
        raise_error(ERR_INVALID_REQUEST, "condition is required and must be a non-empty string")
    line = get_or_404("order_lines", reservation["order_line_id"])
    # priority 8f: over-receipt — input >= 1, reservation ceiling, line remaining
    if received < 1:
        raise_error(ERR_OVER_RECEIPT, "received_units must be at least 1")
    if reservation["received_units"] + received > reservation["units"]:
        raise_error(ERR_OVER_RECEIPT, "receipt would exceed the reservation's units")
    line_remaining = line["quantity"] - line.get("received_units", 0)
    if received > line_remaining:
        raise_error(ERR_OVER_RECEIPT, "receipt would exceed the line's remaining unreceived quantity")
    reservation["received_units"] += received
    reservation["status"] = "OCCUPIED"
    touch(reservation)
    recompute_line_received(line)
    if condition == "DAMAGED":
        # auto-create a warehouse punch item on the line's order and line
        punch = new_entity("punch_items", {
            "order_id": line["order_id"],
            "order_line_id": line["id"],
            "install_event_id": None,
            "severity": "STANDARD",
            "description": f"DAMAGED warehouse receipt of {received} unit(s) against reservation {reservation['id']}",
            "source": "WAREHOUSE",
            "affected_units": 1,
            "status": "OPEN",
        })
        order = db["project_orders"].get(line["order_id"])
        if order is not None:
            recompute_install_posture(order)
    return success_object(public(reservation))


@bp.route("/api/staging-reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(reservation_id):
    authorize(["WarehouseLead"])
    reservation = get_or_404("staging_reservations", reservation_id)
    if reservation["status"] != "OCCUPIED":
        raise_error(ERR_INVALID_STATE, f"cannot release a reservation in status {reservation['status']}")
    reservation["status"] = "RELEASED"
    touch(reservation)
    return success_object(public(reservation))


@bp.route("/api/staging-reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    authorize(["ProjectManager"])
    reservation = get_or_404("staging_reservations", reservation_id)
    if reservation["status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, f"cannot cancel a reservation in status {reservation['status']}")
    reservation["status"] = "CANCELLED"
    touch(reservation)
    return success_object(public(reservation))
