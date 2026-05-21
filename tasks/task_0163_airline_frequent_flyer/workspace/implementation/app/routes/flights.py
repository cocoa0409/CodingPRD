"""Flight endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock, parse_iso
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, get_flight_or_404,
)
from ..services.serialize import serialize_flight


flights_bp = Blueprint("flights", __name__)


VALID_REGIONS = {"DOMESTIC", "INTERNATIONAL"}


def _validate_flight_create_body(body: dict) -> None:
    require_fields(
        body, "flight_number", "origin", "destination", "distance_miles",
        "route_region", "departure_at", "base_fare_cents",
    )
    if not isinstance(body["flight_number"], str) or not body["flight_number"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid flight_number.")
    for k in ("origin", "destination"):
        if not isinstance(body[k], str) or len(body[k]) != 3 or not body[k].isalpha():
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, f"Invalid {k}.")
    if not isinstance(body["distance_miles"], int) or body["distance_miles"] <= 0:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "distance_miles must be a positive integer.")
    if body["route_region"] not in VALID_REGIONS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid route_region.")
    if not isinstance(body["base_fare_cents"], int) or body["base_fare_cents"] < 0:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "base_fare_cents must be a non-negative integer.")
    for cap_field, default in (("capacity_economy", 100), ("capacity_business", 16), ("capacity_first", 4)):
        if cap_field in body and body[cap_field] is not None:
            if not isinstance(body[cap_field], int) or body[cap_field] < 0:
                raise E.ApiError(E.ERR_INVALID_REQUEST, 400, f"Invalid {cap_field}.")


@flights_bp.post("/flights")
@require_roles("ProgramAdmin")
def create_flight():
    body = get_json_body()
    _validate_flight_create_body(body)
    try:
        dep = parse_iso(body["departure_at"])
    except Exception:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid departure_at.")
    now = clock.now()
    fid = new_uuid()
    f = {
        "id": fid,
        "flight_number": body["flight_number"].strip(),
        "origin": body["origin"].upper(),
        "destination": body["destination"].upper(),
        "distance_miles": body["distance_miles"],
        "route_region": body["route_region"],
        "departure_at": dep,
        "status": "SCHEDULED",
        "base_fare_cents": body["base_fare_cents"],
        "capacity_economy": body.get("capacity_economy") if body.get("capacity_economy") is not None else 100,
        "capacity_business": body.get("capacity_business") if body.get("capacity_business") is not None else 16,
        "capacity_first": body.get("capacity_first") if body.get("capacity_first") is not None else 4,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.flights[fid] = f
    return ok_object(serialize_flight(f), 201)


@flights_bp.get("/flights")
@require_roles("Member", "BookingAgent", "ProgramAdmin")
def list_flights():
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    region_f = request.args.get("route_region")
    items = [
        f for f in store.flights.values()
        if (status_f is None or f["status"] == status_f)
        and (region_f is None or f["route_region"] == region_f)
    ]
    items.sort(key=lambda f: f["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_flight(f) for f in page]
    return ok_array(data, limit, offset, total, has_more)


@flights_bp.get("/flights/<flight_id>")
@require_roles("Member", "BookingAgent", "ProgramAdmin")
def get_flight(flight_id):
    f = get_flight_or_404(flight_id)
    return ok_object(serialize_flight(f))


@flights_bp.post("/flights/<flight_id>/depart")
@require_roles("ProgramAdmin")
def depart_flight(flight_id):
    f = get_flight_or_404(flight_id)
    if f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_BOOKABLE, 409, "Flight cannot be marked departed from this state.")
    f["status"] = "DEPARTED"
    bump_version(f)
    # Implicit upgrade-promotion sweep on this flight (PRD §3.4).
    from ..services.sweeps import promote_upgrades_for_flight
    promote_upgrades_for_flight(f["id"])
    return ok_object(serialize_flight(f))


@flights_bp.post("/flights/<flight_id>/cancel")
@require_roles("ProgramAdmin")
def cancel_flight(flight_id):
    f = get_flight_or_404(flight_id)
    if f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_CANCELLABLE, 409, "Flight cannot be cancelled from this state.")
    f["status"] = "CANCELLED"
    bump_version(f)
    # Cascade: all FlightSegment for this flight in BOOKED -> CANCELLED, plus their WAITLISTED upgrades.
    from ..services.cascade import cascade_flight_cancel
    cascade_flight_cancel(f["id"])
    return ok_object(serialize_flight(f))
