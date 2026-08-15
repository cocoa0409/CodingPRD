"""Flight endpoints (PRD 3.1, 3.7, 3.8)."""

from flask import Blueprint

import db
import serializers
import services
from envelope import success_list, success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FLIGHT_NOT_OPEN,
    ERR_FLIGHT_NOT_CLOSED,
    ERR_DRAFT_PLANS_EXIST,
)
from middleware import require_roles, ALL_ROLES
from timeutil import parse_instant
from util import (
    apply_eq_filter,
    get_json_body,
    paginate,
    parse_pagination,
    require_bool,
    require_int,
    require_number,
    require_string,
    require_ts,
    sort_created_asc,
)

bp = Blueprint("flights", __name__)


def get_flight_or_404(flight_id: str) -> dict:
    flight = db.flights.get(flight_id)
    if flight is None:
        raise_err(ERR_NOT_FOUND, f"Flight {flight_id} not found")
    return flight


@bp.route("/flights", methods=["POST"])
@require_roles("CapacityController")
def create_flight(_user_id: str, _role: str):
    body = get_json_body()
    flight = {
        "flight_number": require_string(body, "flight_number"),
        "origin": require_string(body, "origin"),
        "destination": require_string(body, "destination"),
        "scheduled_departure": require_ts(body, "scheduled_departure"),
        "scheduled_arrival": require_ts(body, "scheduled_arrival"),
        "max_payload_kg": require_number(body, "max_payload_kg"),
        "max_volume_m3": require_number(body, "max_volume_m3"),
        "uld_position_count": require_int(body, "uld_position_count"),
        "dg_certified": require_bool(body, "dg_certified"),
        "weight_restriction_kg": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(flight)
    db.flights[flight["id"]] = flight
    return success_object(serializers.flight(flight), 201)


@bp.route("/flights", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_flights(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_eq_filter(list(db.flights.values()), "status")
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.flight(f) for f in page], limit, offset, total)


@bp.route("/flights/<flight_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_flight(flight_id: str, _user_id: str, _role: str):
    return success_object(serializers.flight(get_flight_or_404(flight_id)))


@bp.route("/flights/<flight_id>/open", methods=["POST"])
@require_roles("CapacityController")
def open_flight(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    if flight["status"] != "SCHEDULED":
        raise_err(ERR_FLIGHT_NOT_OPEN, "Flight must be SCHEDULED to open")
    flight["status"] = "OPEN_FOR_BOOKING"
    db.touch(flight)
    return success_object(serializers.flight(flight))


@bp.route("/flights/<flight_id>/close", methods=["POST"])
@require_roles("CapacityController")
def close_flight(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    if flight["status"] != "OPEN_FOR_BOOKING":
        raise_err(ERR_FLIGHT_NOT_OPEN, "Flight must be OPEN_FOR_BOOKING to close")
    for plan in db.build_up_plans.values():
        if plan["flight_id"] == flight["id"] and plan["status"] == "DRAFT":
            raise_err(ERR_DRAFT_PLANS_EXIST, "A DRAFT build-up plan exists on this flight")
    flight["status"] = "CLOSED"
    db.touch(flight)
    return success_object(serializers.flight(flight))


@bp.route("/flights/<flight_id>/depart", methods=["POST"])
@require_roles("CapacityController")
def depart_flight(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    if flight["status"] != "CLOSED":
        raise_err(ERR_FLIGHT_NOT_CLOSED, "Flight must be CLOSED to depart")
    services.depart_flight(flight)
    return success_object(serializers.flight(flight))


@bp.route("/flights/<flight_id>/weight-restriction", methods=["POST"])
@require_roles("CapacityController")
def weight_restriction(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    body = get_json_body()
    # rung 4: 0 < restricted_payload_kg <= max_payload_kg
    restricted = require_number(body, "restricted_payload_kg")
    restricted_d = services.dec(restricted)
    if restricted_d <= 0 or restricted_d > services.dec(flight["max_payload_kg"]):
        raise_err(
            ERR_INVALID_REQUEST,
            "restricted_payload_kg must be greater than 0 and no more than max_payload_kg",
        )
    # rung 6: OPEN_FOR_BOOKING or CLOSED
    if flight["status"] not in ("OPEN_FOR_BOOKING", "CLOSED"):
        raise_err(
            ERR_FLIGHT_NOT_OPEN,
            "Weight restriction requires flight OPEN_FOR_BOOKING or CLOSED",
        )
    # record the restriction itself
    flight["weight_restriction_kg"] = restricted
    db.touch(flight)

    # offload_selection (scaffold calculations): newest-created first, then
    # gross_weight_kg DESC, then volume_m3 DESC; whole bookings only.
    if services.allocated_weight_kg(flight["id"]) > restricted_d:
        candidates = [
            b for b in services.bookings_on_flight(flight["id"])
            if b["status"] in services.ALLOCATED_STATUSES
        ]
        candidates.sort(
            key=lambda b: (
                parse_instant(b["created_at"]),
                services.dec(b["gross_weight_kg"]),
                services.dec(b["volume_m3"]),
                b["_seq"],
            ),
            reverse=True,
        )
        for booking in candidates:
            if services.allocated_weight_kg(flight["id"]) <= restricted_d:
                break
            services.offload_booking(booking, flight)
    return success_object(serializers.flight(flight))


@bp.route("/flights/<flight_id>/bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_flight_bookings(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    limit, offset = parse_pagination()
    items = [b for b in db.bookings.values() if b["flight_id"] == flight["id"]]
    items = apply_eq_filter(items, "status")
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.booking(b) for b in page], limit, offset, total)


@bp.route("/flights/<flight_id>/build-up-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_flight_plans(flight_id: str, _user_id: str, _role: str):
    flight = get_flight_or_404(flight_id)
    limit, offset = parse_pagination()
    items = [p for p in db.build_up_plans.values() if p["flight_id"] == flight["id"]]
    items = apply_eq_filter(items, "status")
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.build_up_plan(p) for p in page], limit, offset, total)
