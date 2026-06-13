"""Depot and BayReservation routes (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response

bp = Blueprint("depots", __name__)


@bp.route("/depots", methods=["POST"])
def create_depot():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, ["name", "lat", "lng", "bay_count", "cleanup_buffer_minutes"])
    validation.require_str(body["name"], "name")
    validation.require_lat(body["lat"], "lat")
    validation.require_lng(body["lng"], "lng")

    bay_count = body["bay_count"]
    if not validation.is_int(bay_count) or bay_count < 1:
        raise errors.invalid_request("bay_count must be an integer >= 1.")

    buf = body["cleanup_buffer_minutes"]
    if not validation.is_int(buf) or buf < 0:
        raise errors.invalid_request("cleanup_buffer_minutes must be an integer >= 0.")

    record = {
        "name": body["name"],
        "lat": body["lat"],
        "lng": body["lng"],
        "bay_count": bay_count,
        "cleanup_buffer_minutes": buf,
        "occupied_bays": 0,
    }
    db.stamp_create(record)
    db.depots[record["id"]] = record
    return object_response(serializers.depot(record), 201)


@bp.route("/depots/<depot_id>", methods=["GET"])
def get_depot(depot_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider", "Member"})
    d = db.depots.get(depot_id)
    if d is None:
        raise errors.not_found("Depot not found.")
    return object_response(serializers.depot(d), 200)


@bp.route("/depots", methods=["GET"])
def list_depots():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider", "Member"})
    limit, offset = validation.parse_pagination()
    records = list(db.depots.values())
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.depot(d) for d in page],
                          limit, offset, total, 200)


def _buffered_window(reservation, depot):
    rf = validation.parse_datetime(reservation["reserved_from"], "reserved_from")
    ru = validation.parse_datetime(reservation["reserved_until"], "reserved_until")
    ru_buffered = ru + timedelta(minutes=depot["cleanup_buffer_minutes"])
    return rf, ru_buffered


@bp.route("/depots/<depot_id>/bay-reservations", methods=["POST"])
def create_reservation(depot_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    d = db.depots.get(depot_id)
    if d is None:
        raise errors.not_found("Depot not found.")

    body = validation.get_body()
    validation.require_present(body, ["service_call_id", "reserved_from", "reserved_until"])

    service_call_id = body["service_call_id"]
    if not isinstance(service_call_id, str):
        raise errors.invalid_request("service_call_id must be a string.")
    call = db.service_calls.get(service_call_id)
    if call is None:
        raise errors.not_found("Service call not found.")

    reserved_from = validation.parse_datetime(body["reserved_from"], "reserved_from")
    reserved_until = validation.parse_datetime(body["reserved_until"], "reserved_until")
    if reserved_until < reserved_from:
        raise errors.invalid_request("reserved_until may not be earlier than reserved_from.")

    # Aggregate-capacity overlap: count ACTIVE reservations whose buffered
    # closed windows overlap the new request's buffered closed window.
    new_from = reserved_from
    new_until_buffered = reserved_until + timedelta(minutes=d["cleanup_buffer_minutes"])
    overlapping = 0
    for r in db.bay_reservations.values():
        if r["depot_id"] != depot_id or r["status"] != "ACTIVE":
            continue
        ef, eu = _buffered_window(r, d)
        # Closed-interval overlap: new_from <= eu and ef <= new_until_buffered.
        if new_from <= eu and ef <= new_until_buffered:
            overlapping += 1
    if overlapping >= d["bay_count"]:
        raise errors.ApiError(errors.ERR_NO_BAY_AVAILABLE, 409,
                              "No bay available across the buffered window.")

    record = {
        "depot_id": depot_id,
        "service_call_id": service_call_id,
        "reserved_from": body["reserved_from"],
        "reserved_until": body["reserved_until"],
        "status": "ACTIVE",
    }
    db.stamp_create(record)
    db.bay_reservations[record["id"]] = record
    d["occupied_bays"] += 1
    db.touch(d)
    return object_response(serializers.bay_reservation(record), 201)


@bp.route("/depots/<depot_id>/bay-reservations", methods=["GET"])
def list_reservations(depot_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    d = db.depots.get(depot_id)
    if d is None:
        raise errors.not_found("Depot not found.")
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    service_call_id = request.args.get("service_call_id")
    records = [r for r in db.bay_reservations.values() if r["depot_id"] == depot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if service_call_id is not None:
        records = [r for r in records if r["service_call_id"] == service_call_id]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.bay_reservation(r) for r in page],
                          limit, offset, total, 200)


@bp.route("/depots/<depot_id>/bay-reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(depot_id, reservation_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    d = db.depots.get(depot_id)
    if d is None:
        raise errors.not_found("Depot not found.")
    r = db.bay_reservations.get(reservation_id)
    if r is None or r["depot_id"] != depot_id:
        raise errors.not_found("Bay reservation not found.")
    if r["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE reservation may be released.")
    r["status"] = "RELEASED"
    db.touch(r)
    d["occupied_bays"] -= 1
    db.touch(d)
    return object_response(serializers.bay_reservation(r), 200)
