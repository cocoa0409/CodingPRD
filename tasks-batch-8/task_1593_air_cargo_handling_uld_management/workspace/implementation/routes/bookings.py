"""Booking endpoints plus booking-scoped sub-resources (DG declarations,
temperature logs, customs holds, claims lists) — PRD 3.2, 3.3, 3.5, 3.6."""

from flask import Blueprint

import db
import serializers
import services
from envelope import success_list, success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_BOOKING_NOT_OWNED,
    ERR_BOOKING_INVALID_STATE,
    ERR_FLIGHT_NOT_OPEN,
    ERR_FLIGHT_NOT_DG_CERTIFIED,
    ERR_FLIGHT_PAYLOAD_EXCEEDED,
    ERR_FLIGHT_VOLUME_EXCEEDED,
    ERR_DG_CHECK_ALREADY_PENDING,
    ERR_DG_NOT_APPLICABLE,
    ERR_HOLD_ALREADY_ACTIVE,
    ERR_TEMP_RANGE_NOT_DEFINED,
)
from middleware import require_roles, ALL_ROLES
from util import (
    get_json_body,
    optional_bool,
    optional_number,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    require_ts,
    sort_created_asc,
)

bp = Blueprint("bookings", __name__)


def get_booking_or_404(booking_id: str) -> dict:
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise_err(ERR_NOT_FOUND, f"Booking {booking_id} not found")
    return booking


def check_flight_capacity(flight: dict, booking: dict) -> None:
    """flight_capacity_check (rungs 13 then 14); equality is accepted, only a
    strictly-greater overflow is rejected."""
    if services.allocated_weight_kg(flight["id"]) + services.dec(booking["gross_weight_kg"]) > services.dec(
        flight["max_payload_kg"]
    ):
        raise_err(ERR_FLIGHT_PAYLOAD_EXCEEDED, "Flight payload capacity exceeded")
    if services.allocated_volume_m3(flight["id"]) + services.dec(booking["volume_m3"]) > services.dec(
        flight["max_volume_m3"]
    ):
        raise_err(ERR_FLIGHT_VOLUME_EXCEEDED, "Flight volume capacity exceeded")


# ---------------------------------------------------------------------------
# Booking intake
# ---------------------------------------------------------------------------

@bp.route("/bookings", methods=["POST"])
@require_roles("ForwarderAgent")
def create_booking(_user_id: str, _role: str):
    body = get_json_body()
    # rung 3: identifiers referenced in the body must exist (before shape).
    flight_ref = body.get("flight_id")
    if flight_ref is not None and flight_ref not in db.flights:
        raise_err(ERR_NOT_FOUND, f"Flight {flight_ref} not found")
    # rung 4: request shape.
    flight_id = require_string(body, "flight_id")
    shipper_ref = require_string(body, "shipper_ref")
    commodity_code = require_string(body, "commodity_code")
    pieces = require_int(body, "pieces")
    if pieces < 1:
        raise_err(ERR_INVALID_REQUEST, "pieces must be at least 1")
    gross_weight = require_number(body, "gross_weight_kg")
    if services.dec(gross_weight) <= 0:
        raise_err(ERR_INVALID_REQUEST, "gross_weight_kg must be greater than 0")
    volume = require_number(body, "volume_m3")
    if services.dec(volume) <= 0:
        raise_err(ERR_INVALID_REQUEST, "volume_m3 must be greater than 0")
    is_dg = optional_bool(body, "is_dangerous_goods", False)
    temp_min = optional_number(body, "temp_min_c")
    temp_max = optional_number(body, "temp_max_c")
    if (temp_min is None) != (temp_max is None):
        raise_err(
            ERR_INVALID_REQUEST,
            "temp_min_c and temp_max_c must be set together or not at all",
        )
    if temp_min is not None and services.dec(temp_min) > services.dec(temp_max):
        raise_err(ERR_INVALID_REQUEST, "temp_min_c must not exceed temp_max_c")
    declared_value = optional_number(body, "declared_value")

    booking = {
        "flight_id": flight_id,
        "shipper_ref": shipper_ref,
        "commodity_code": commodity_code,
        "pieces": pieces,
        "gross_weight_kg": gross_weight,
        "volume_m3": volume,
        "chargeable_weight_kg": services.chargeable_weight_kg(gross_weight, volume),
        "is_dangerous_goods": is_dg,
        "temp_min_c": temp_min,
        "temp_max_c": temp_max,
        "declared_value": declared_value,
        "temp_excursion_count": 0,
        "temp_status": "NOT_MONITORED",
        "build_up_plan_id": None,
        "created_by_user_id": _user_id,
        "status": "REQUESTED",
    }
    db.stamp_new(booking)
    db.bookings[booking["id"]] = booking
    return success_object(serializers.booking(booking), 201)


@bp.route("/bookings/<booking_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_booking(booking_id: str, _user_id: str, _role: str):
    return success_object(serializers.booking(get_booking_or_404(booking_id)))


@bp.route("/bookings/<booking_id>/accept", methods=["POST"])
@require_roles("CapacityController")
def accept_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    # rung 6: state preconditions
    if booking["status"] != "REQUESTED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Accept requires booking REQUESTED")
    flight = db.flights[booking["flight_id"]]
    if flight["status"] != "OPEN_FOR_BOOKING":
        raise_err(ERR_FLIGHT_NOT_OPEN, "Flight must be OPEN_FOR_BOOKING")
    # rung 7: dangerous-goods embargo
    if booking["is_dangerous_goods"] and not flight["dg_certified"]:
        raise_err(ERR_FLIGHT_NOT_DG_CERTIFIED, "Flight is not dangerous-goods certified")
    # rungs 13-14: payload then volume
    check_flight_capacity(flight, booking)
    booking["status"] = "ACCEPTED"
    db.touch(booking)
    db.touch(flight)  # allocation debited -> Flight.version increments
    return success_object(serializers.booking(booking))


@bp.route("/bookings/<booking_id>/reject", methods=["POST"])
@require_roles("CapacityController")
def reject_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    get_json_body()  # optional reason; not persisted on the resource
    if booking["status"] != "REQUESTED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Reject requires booking REQUESTED")
    booking["status"] = "REJECTED"
    db.touch(booking)
    return success_object(serializers.booking(booking))


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@require_roles("ForwarderAgent")
def cancel_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    # rung 5 (attribute authorization) precedes rung 6 (state).
    if booking["created_by_user_id"] != _user_id:
        raise_err(ERR_BOOKING_NOT_OWNED, "Booking is owned by another forwarder")
    if booking["status"] not in ("REQUESTED", "ACCEPTED"):
        raise_err(
            ERR_BOOKING_INVALID_STATE, "Cancel requires booking REQUESTED or ACCEPTED"
        )
    was_accepted = booking["status"] == "ACCEPTED"
    booking["status"] = "CANCELLED"
    db.touch(booking)
    if was_accepted:
        # compensate the acceptance debit on the flight
        db.touch(db.flights[booking["flight_id"]])
    return success_object(serializers.booking(booking))


@bp.route("/bookings/<booking_id>/rebook", methods=["POST"])
@require_roles("CapacityController")
def rebook_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    body = get_json_body()
    # rung 3: target flight referenced in the body must exist.
    flight_ref = body.get("flight_id")
    if flight_ref is not None and flight_ref not in db.flights:
        raise_err(ERR_NOT_FOUND, f"Flight {flight_ref} not found")
    target_id = require_string(body, "flight_id")
    # rung 6: state preconditions
    if booking["status"] != "OFFLOADED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Rebook requires booking OFFLOADED")
    target = db.flights[target_id]
    if target["status"] != "OPEN_FOR_BOOKING":
        raise_err(ERR_FLIGHT_NOT_OPEN, "Target flight must be OPEN_FOR_BOOKING")
    # rung 7: dangerous-goods embargo (exactly as at acceptance)
    if booking["is_dangerous_goods"] and not target["dg_certified"]:
        raise_err(ERR_FLIGHT_NOT_DG_CERTIFIED, "Target flight is not dangerous-goods certified")
    # rungs 13-14 against the target flight, payload then volume
    check_flight_capacity(target, booking)
    booking["flight_id"] = target_id
    booking["status"] = "ACCEPTED"
    db.touch(booking)
    db.touch(target)  # target flight allocation debited
    return success_object(serializers.booking(booking))


# ---------------------------------------------------------------------------
# DG declarations (booking-scoped create/list; PRD 3.3)
# ---------------------------------------------------------------------------

@bp.route("/bookings/<booking_id>/dg-declarations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_dg_declarations(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [d for d in db.dg_declarations.values() if d["booking_id"] == booking["id"]]
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.dg_declaration(d) for d in page], limit, offset, total)


@bp.route("/bookings/<booking_id>/dg-declarations", methods=["POST"])
@require_roles("ForwarderAgent")
def create_dg_declaration(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    body = get_json_body()
    # rung 4: shape
    un_number = require_string(body, "un_number")
    dg_class = require_string(body, "dg_class")
    packing_group = require_enum(body, "packing_group", ("I", "II", "III"))
    declaration_doc_ref = require_string(body, "declaration_doc_ref")
    # rung 5: ownership (attribute authorization precedes state)
    if booking["created_by_user_id"] != _user_id:
        raise_err(ERR_BOOKING_NOT_OWNED, "Booking is owned by another forwarder")
    # rung 6: booking still early in its pipeline; at most one PENDING_CHECK
    if booking["status"] not in ("REQUESTED", "ACCEPTED", "BUILT_UP"):
        raise_err(
            ERR_BOOKING_INVALID_STATE,
            "DG declaration requires booking REQUESTED, ACCEPTED or BUILT_UP",
        )
    if services.pending_declaration_for_booking(booking["id"]) is not None:
        raise_err(
            ERR_DG_CHECK_ALREADY_PENDING,
            "A PENDING_CHECK declaration already exists for this booking",
        )
    # rung 10: referential coherence
    if not booking["is_dangerous_goods"]:
        raise_err(
            ERR_DG_NOT_APPLICABLE,
            "Booking was not tendered as dangerous goods",
        )
    declaration = {
        "booking_id": booking["id"],
        "un_number": un_number,
        "dg_class": dg_class,
        "packing_group": packing_group,
        "declaration_doc_ref": declaration_doc_ref,
        "checked_by_user_id": None,
        "rejection_reason": None,
        "status": "PENDING_CHECK",
    }
    db.stamp_new(declaration)
    db.dg_declarations[declaration["id"]] = declaration
    return success_object(serializers.dg_declaration(declaration), 201)


# ---------------------------------------------------------------------------
# Temperature logs (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.route("/bookings/<booking_id>/temperature-logs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_temperature_logs(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [t for t in db.temperature_logs.values() if t["booking_id"] == booking["id"]]
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.temperature_log(t) for t in page], limit, offset, total)


@bp.route("/bookings/<booking_id>/temperature-logs", methods=["POST"])
@require_roles("RampOperator")
def create_temperature_log(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    body = get_json_body()
    recorded_at = require_ts(body, "recorded_at")
    temperature = require_number(body, "temperature_c")
    # rung 6: booking must be in the handler's operational flow
    if booking["status"] not in ("ACCEPTED", "BUILT_UP", "LOADED"):
        raise_err(
            ERR_BOOKING_INVALID_STATE,
            "Temperature log requires booking ACCEPTED, BUILT_UP or LOADED",
        )
    # rung 10: the booking must define a temperature range
    if booking["temp_min_c"] is None or booking["temp_max_c"] is None:
        raise_err(ERR_TEMP_RANGE_NOT_DEFINED, "Booking defines no temperature range")

    # temperature_excursion_check: bounds inclusive
    temp_d = services.dec(temperature)
    in_range = (
        services.dec(booking["temp_min_c"]) <= temp_d <= services.dec(booking["temp_max_c"])
    )
    log = {
        "booking_id": booking["id"],
        "recorded_at": recorded_at,
        "temperature_c": temperature,
        "in_range": in_range,
    }
    db.stamp_new_light(log)
    db.temperature_logs[log["id"]] = log
    if not in_range:
        booking["temp_excursion_count"] += 1
        booking["temp_status"] = "EXCURSION"  # sticky: never returns to IN_RANGE
        db.touch(booking)
    elif booking["temp_status"] == "NOT_MONITORED":
        booking["temp_status"] = "IN_RANGE"
        db.touch(booking)
    return success_object(serializers.temperature_log(log), 201)


# ---------------------------------------------------------------------------
# Customs holds (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route("/bookings/<booking_id>/customs-holds", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_customs_holds(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [h for h in db.customs_holds.values() if h["booking_id"] == booking["id"]]
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.customs_hold(h) for h in page], limit, offset, total)


@bp.route("/bookings/<booking_id>/customs-holds", methods=["POST"])
@require_roles("CustomsOfficer")
def create_customs_hold(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    body = get_json_body()
    reason_code = require_string(body, "reason_code")
    # rung 6: pre-departure pipeline + at most one ACTIVE hold per booking
    if booking["status"] not in ("REQUESTED", "ACCEPTED", "BUILT_UP"):
        raise_err(
            ERR_BOOKING_INVALID_STATE,
            "Customs hold requires booking REQUESTED, ACCEPTED or BUILT_UP",
        )
    if services.active_hold_for_booking(booking["id"]) is not None:
        raise_err(ERR_HOLD_ALREADY_ACTIVE, "An ACTIVE customs hold already exists")
    hold = {
        "booking_id": booking["id"],
        "reason_code": reason_code,
        "placed_at": db.now_iso(),
        "released_at": None,
        "release_note": None,
        "status": "ACTIVE",
    }
    db.stamp_new(hold)
    db.customs_holds[hold["id"]] = hold
    return success_object(serializers.customs_hold(hold), 201)


# ---------------------------------------------------------------------------
# Claims list (booking-scoped; PRD 3.9)
# ---------------------------------------------------------------------------

@bp.route("/bookings/<booking_id>/claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_booking_claims(booking_id: str, _user_id: str, _role: str):
    booking = get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [c for c in db.claims.values() if c["booking_id"] == booking["id"]]
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.claim(c) for c in page], limit, offset, total)
