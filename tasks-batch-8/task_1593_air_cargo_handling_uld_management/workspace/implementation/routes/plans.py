"""Build-up plan endpoints (PRD 3.4): create (OCC on Flight.version),
assign (OCC on BuildUpPlan.version), seal, cancel, plus sub-lists."""

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
    ERR_ULD_NOT_SERVICEABLE,
    ERR_STALE_FLIGHT_VERSION,
    ERR_STALE_PLAN_VERSION,
    ERR_BUILD_WINDOW_CONFLICT,
    ERR_ULD_POSITION_UNAVAILABLE,
    ERR_PLAN_NOT_DRAFT,
    ERR_PLAN_NOT_CANCELLABLE,
    ERR_PLAN_EMPTY,
    ERR_BOOKING_NOT_ACCEPTED,
    ERR_CUSTOMS_HOLD_ACTIVE,
    ERR_DG_NOT_ACCEPTED,
    ERR_BOOKING_FLIGHT_MISMATCH,
    ERR_ULD_PAYLOAD_EXCEEDED,
)
from middleware import require_roles, ALL_ROLES
from util import (
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    require_ts,
    sort_created_asc,
)
from timeutil import parse_instant

bp = Blueprint("plans", __name__)


def get_plan_or_404(plan_id: str) -> dict:
    plan = db.build_up_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, f"BuildUpPlan {plan_id} not found")
    return plan


@bp.route("/build-up-plans", methods=["POST"])
@require_roles("RampOperator")
def create_plan(_user_id: str, _role: str):
    body = get_json_body()
    # rung 3: identifiers referenced in the body must exist (flight, then uld).
    flight_ref = body.get("flight_id")
    if flight_ref is not None and flight_ref not in db.flights:
        raise_err(ERR_NOT_FOUND, f"Flight {flight_ref} not found")
    uld_ref = body.get("uld_id")
    if uld_ref is not None and uld_ref not in db.ulds:
        raise_err(ERR_NOT_FOUND, f"ULD {uld_ref} not found")
    # rung 4: shape — build_end strictly later than build_start; OCC token int.
    flight_id = require_string(body, "flight_id")
    uld_id = require_string(body, "uld_id")
    build_start = require_ts(body, "build_start")
    build_end = require_ts(body, "build_end")
    if parse_instant(build_end) <= parse_instant(build_start):
        raise_err(ERR_INVALID_REQUEST, "build_end must be strictly later than build_start")
    expected_flight_version = require_int(body, "expected_flight_version")

    flight = db.flights[flight_id]
    uld = db.ulds[uld_id]
    # rung 6: state preconditions (flight open, unit serviceable, OCC).
    if flight["status"] != "OPEN_FOR_BOOKING":
        raise_err(ERR_FLIGHT_NOT_OPEN, "Flight must be OPEN_FOR_BOOKING")
    if uld["status"] != "SERVICEABLE":
        raise_err(ERR_ULD_NOT_SERVICEABLE, "ULD must be SERVICEABLE")
    if expected_flight_version != flight["version"]:
        raise_err(
            ERR_STALE_FLIGHT_VERSION,
            "expected_flight_version does not match the flight's current version",
        )
    # rung 11: 30-minute build-window separation on the same flight.
    if services.build_window_conflict(flight_id, build_start, build_end):
        raise_err(
            ERR_BUILD_WINDOW_CONFLICT,
            "Build window violates the 30-minute separation buffer",
        )
    # rung 12: a free ULD position must exist.
    if services.reserved_positions(flight_id) >= flight["uld_position_count"]:
        raise_err(ERR_ULD_POSITION_UNAVAILABLE, "Flight has no free ULD position")

    plan = {
        "flight_id": flight_id,
        "uld_id": uld_id,
        "build_start": build_start,
        "build_end": build_end,
        "status": "DRAFT",
    }
    db.stamp_new(plan)
    db.build_up_plans[plan["id"]] = plan
    uld["status"] = "ASSIGNED"
    db.touch(uld)
    db.touch(flight)  # reserved_positions += 1 -> Flight.version increments
    return success_object(serializers.build_up_plan(plan), 201)


@bp.route("/build-up-plans/<plan_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan(plan_id: str, _user_id: str, _role: str):
    return success_object(serializers.build_up_plan(get_plan_or_404(plan_id)))


@bp.route("/build-up-plans/<plan_id>/bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plan_bookings(plan_id: str, _user_id: str, _role: str):
    plan = get_plan_or_404(plan_id)
    limit, offset = parse_pagination()
    items = sort_created_asc(services.bookings_on_plan(plan["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.booking(b) for b in page], limit, offset, total)


@bp.route("/build-up-plans/<plan_id>/assign", methods=["POST"])
@require_roles("RampOperator")
def assign_booking(plan_id: str, _user_id: str, _role: str):
    plan = get_plan_or_404(plan_id)
    body = get_json_body()
    # rung 3: booking referenced in the body must exist.
    booking_ref = body.get("booking_id")
    if booking_ref is not None and booking_ref not in db.bookings:
        raise_err(ERR_NOT_FOUND, f"Booking {booking_ref} not found")
    # rung 4: shape
    booking_id = require_string(body, "booking_id")
    expected_plan_version = require_int(body, "expected_build_up_plan_version")
    booking = db.bookings[booking_id]

    # rung 6: state first — plan DRAFT, booking ACCEPTED, then the OCC token.
    if plan["status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_DRAFT, "Assign requires plan DRAFT")
    if booking["status"] != "ACCEPTED":
        raise_err(ERR_BOOKING_NOT_ACCEPTED, "Assign requires booking ACCEPTED")
    if expected_plan_version != plan["version"]:
        raise_err(
            ERR_STALE_PLAN_VERSION,
            "expected_build_up_plan_version does not match the plan's current version",
        )
    # rung 8: customs gate
    if services.active_hold_for_booking(booking["id"]) is not None:
        raise_err(ERR_CUSTOMS_HOLD_ACTIVE, "Booking has an ACTIVE customs hold")
    # rung 9: dangerous-goods documentation gate
    if booking["is_dangerous_goods"] and services.accepted_declaration_for_booking(
        booking["id"]
    ) is None:
        raise_err(ERR_DG_NOT_ACCEPTED, "Dangerous-goods booking lacks an ACCEPTED declaration")
    # rung 10: referential coherence — cargo is never cross-loaded
    if booking["flight_id"] != plan["flight_id"]:
        raise_err(ERR_BOOKING_FLIGHT_MISMATCH, "Booking flight does not match plan flight")
    # rung 12: ULD payload — tare + plan total + candidate gross <= max
    uld = db.ulds[plan["uld_id"]]
    uld_type = db.uld_types[uld["uld_type_id"]]
    projected = (
        services.dec(uld_type["tare_weight_kg"])
        + services.plan_total_weight_kg(plan["id"])
        + services.dec(booking["gross_weight_kg"])
    )
    if projected > services.dec(uld_type["max_gross_weight_kg"]):
        raise_err(ERR_ULD_PAYLOAD_EXCEEDED, "ULD payload would exceed maximum gross weight")

    booking["status"] = "BUILT_UP"
    booking["build_up_plan_id"] = plan["id"]
    db.touch(booking)
    db.touch(plan)  # total_weight_kg (derived) increased -> plan version bump
    return success_object(serializers.build_up_plan(plan))


@bp.route("/build-up-plans/<plan_id>/seal", methods=["POST"])
@require_roles("RampOperator")
def seal_plan(plan_id: str, _user_id: str, _role: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_DRAFT, "Seal requires plan DRAFT")
    if len(services.bookings_on_plan(plan["id"])) < 1:
        raise_err(ERR_PLAN_EMPTY, "Seal requires at least one BUILT_UP booking")
    plan["status"] = "SEALED"
    db.touch(plan)
    return success_object(serializers.build_up_plan(plan))


@bp.route("/build-up-plans/<plan_id>/cancel", methods=["POST"])
@require_roles("RampOperator")
def cancel_plan(plan_id: str, _user_id: str, _role: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] not in ("DRAFT", "SEALED"):
        raise_err(ERR_PLAN_NOT_CANCELLABLE, "Cancel requires plan DRAFT or SEALED")
    # unwind: every BUILT_UP booking returns to ACCEPTED
    for booking in services.bookings_on_plan(plan["id"]):
        booking["status"] = "ACCEPTED"
        booking["build_up_plan_id"] = None
        db.touch(booking)
    plan["status"] = "CANCELLED"
    db.touch(plan)
    uld = db.ulds.get(plan["uld_id"])
    if uld is not None and uld["status"] == "ASSIGNED":
        uld["status"] = "SERVICEABLE"
        db.touch(uld)
    db.touch(db.flights[plan["flight_id"]])  # reserved_positions -= 1
    return success_object(serializers.build_up_plan(plan))
