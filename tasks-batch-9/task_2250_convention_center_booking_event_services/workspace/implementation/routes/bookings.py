"""Bookings and the attested usage days beneath them (PRD 3.2, 3.8)."""

from flask import Blueprint

import calc
import clock
import lookups
import validate
from db import db
from errors import err
from middleware import actor, body, endpoint, filter_rows, require_owner, touch
from response import entity_response
from routes.common import (
    EVENT_CLASSES,
    USAGE_KINDS,
    body_fk,
    listing,
    require_standing,
)
from services import engine
from util import parse_date, whole_months_between

bp = Blueprint("bookings", __name__)

RELEASABLE = ("TENTATIVE", "DEFINITE")


# --------------------------------------------------------------------------
# creation and reads
# --------------------------------------------------------------------------
@bp.post("/bookings")
@endpoint("SalesManager", "VenueAdmin")
def create_booking():
    payload = body()

    # ladder step 5: body references, in the declared field order
    client = body_fk(payload, "client_id", "client")
    space = body_fk(payload, "space_id", "space")

    # ladder step 6: the policy window must be published before the dates are read
    event_class = validate.req_enum(payload, "event_class", EVENT_CLASSES)
    window = lookups.policy_window_for_class(event_class)
    if window is None:
        raise err("ERR_POLICY_WINDOW_MISSING")

    # ladder step 7: body validity
    event_name = validate.req_string(payload, "event_name")
    move_in_start = validate.req_date(payload, "move_in_start_date")
    show_start = validate.req_date(payload, "show_start_date")
    show_end = validate.req_date(payload, "show_end_date")
    move_out_end = validate.req_date(payload, "move_out_end_date")
    room_nights = validate.opt_int(payload, "projected_room_nights", 0, minimum=0)
    if not (move_in_start <= show_start <= show_end <= move_out_end):
        raise err(
            "ERR_INVALID_REQUEST",
            "The four booking dates must be non-decreasing: move_in_start_date <= "
            "show_start_date <= show_end_date <= move_out_end_date.",
        )

    # ladder step 8: citywide qualification
    if event_class == "CITYWIDE_CONVENTION":
        if (
            client["organization_type"] != "NATIONAL_ASSOCIATION"
            or room_nights < calc.CITYWIDE_MIN_ROOM_NIGHTS
        ):
            raise err("ERR_CITYWIDE_QUALIFICATION_NOT_MET")

    # ladder step 15: the booking window, then maintenance clearance
    months_out = whole_months_between(clock.today(), show_start)
    if months_out > window["open_months_before"] or months_out < window["close_months_before"]:
        raise err("ERR_BOOKING_WINDOW_CLOSED")
    if not engine.interval_clears_all_blackouts(space["id"], move_in_start, move_out_end):
        raise err("ERR_MAINTENANCE_BLACKOUT_CONFLICT")

    # ladder step 18: fiscal gates
    require_standing(client)

    gross, contracted, deposit = calc.contracted_rental_charge(
        space, window, move_in_start, show_start, show_end, move_out_end
    )
    space_days = calc.space_days_committed(move_in_start, move_out_end)

    booking = db.insert(
        "booking",
        {
            "client_id": client["id"],
            "space_id": space["id"],
            "policy_window_id": window["id"],
            "event_name": event_name,
            "event_class": event_class,
            "move_in_start_date": move_in_start.isoformat(),
            "show_start_date": show_start.isoformat(),
            "show_end_date": show_end.isoformat(),
            "move_out_end_date": move_out_end.isoformat(),
            "projected_room_nights": room_nights,
            "status": "TENTATIVE",
            "order_posture": "OPEN",
            "gross_rental_cents": gross,
            "contracted_rental_cents": contracted,
            "deposit_required_cents": deposit,
            "space_days_committed": space_days,
            "hold_count": 0,
        },
    )
    engine.adjust_committed_space_days(space["id"], space_days)
    return entity_response(booking, 201)


@bp.get("/bookings")
@endpoint(
    "VenueAdmin",
    "SalesManager",
    "EventServicesManager",
    "SettlementAnalyst",
    "FacilitiesPlanner",
)
def list_bookings():
    rows = filter_rows(
        "booking",
        {
            "client_id": "client_id",
            "space_id": "space_id",
            "policy_window_id": "policy_window_id",
            "status": "status",
        },
    )
    return listing(rows)


@bp.get("/bookings/<booking_id>")
@endpoint(
    "VenueAdmin",
    "SalesManager",
    "EventServicesManager",
    "SettlementAnalyst",
    "FacilitiesPlanner",
    "Licensee",
)
def read_booking(booking_id):
    booking = lookups.fetch("booking", booking_id)
    require_owner(booking["client_id"])
    return entity_response(booking)


# --------------------------------------------------------------------------
# lifecycle transitions
# --------------------------------------------------------------------------
@bp.post("/bookings/<booking_id>/confirm-definite")
@endpoint("SalesManager")
def confirm_definite(booking_id):
    booking = lookups.fetch("booking", booking_id)
    if booking["status"] != "TENTATIVE":
        raise err("ERR_BOOKING_STATE_INVALID")
    holds = lookups.holds_of_booking(booking["id"])
    if not any(h["status"] == "CONFIRMED" for h in holds):
        raise err("ERR_HOLD_STATE_INVALID")
    lic = lookups.live_license_of_booking(booking["id"])
    if lic is None or lic["status"] != "EXECUTED":
        raise err("ERR_LICENSE_STATE_INVALID")
    require_standing(db.clients.get(booking["client_id"]))

    booking["status"] = "DEFINITE"
    touch(booking)
    engine.recompute_order_posture(booking)
    return entity_response(booking)


@bp.post("/bookings/<booking_id>/open-show")
@endpoint("EventServicesManager")
def open_show(booking_id):
    booking = lookups.fetch("booking", booking_id)
    if booking["status"] != "DEFINITE":
        raise err("ERR_BOOKING_STATE_INVALID")
    lic = lookups.live_license_of_booking(booking["id"])
    if lic is None or lic["status"] != "EXECUTED":
        raise err("ERR_LICENSE_STATE_INVALID")
    if clock.today() < parse_date(booking["move_in_start_date"]):
        raise err("ERR_MOVE_IN_NOT_REACHED")

    booking["status"] = "IN_HOUSE"
    touch(booking)
    engine.recompute_order_posture(booking)
    return entity_response(booking)


@bp.post("/bookings/<booking_id>/close")
@endpoint("EventServicesManager")
def close_booking(booking_id):
    booking = lookups.fetch("booking", booking_id)
    if booking["status"] != "IN_HOUSE":
        raise err("ERR_BOOKING_STATE_INVALID")
    if not clock.today() > parse_date(booking["move_out_end_date"]):
        raise err("ERR_EVENT_NOT_ENDED")
    for order in lookups.service_orders_of_booking(booking["id"]):
        if order["billing_status"] not in ("RECONCILED", "VOID"):
            raise err("ERR_SERVICE_ORDERS_NOT_RECONCILED")
    for call in lookups.labor_calls_of_booking(booking["id"]):
        if call["status"] not in ("ACTUALIZED", "CANCELLED"):
            raise err("ERR_SERVICE_ORDERS_NOT_RECONCILED")

    booking["status"] = "CLOSED"
    touch(booking)
    engine.recompute_order_posture(booking)

    for arrangement in lookups.catering_of_booking(booking["id"]):
        if arrangement["status"] != "APPROVED":
            continue
        if arrangement.get("actual_fnb_cents") is None:
            continue
        arrangement["buyout_fee_cents"] = calc.fnb_buyout_fee(
            arrangement, arrangement["actual_fnb_cents"]
        )
        arrangement["status"] = "CLOSED"
        touch(arrangement)
    return entity_response(booking)


@bp.post("/bookings/<booking_id>/release")
@endpoint("SalesManager", "VenueAdmin")
def release_booking_route(booking_id):
    booking = lookups.fetch("booking", booking_id)
    if booking["status"] not in RELEASABLE:
        raise err("ERR_BOOKING_STATE_INVALID")
    if lookups.settlements_of_booking(booking["id"]):
        raise err("ERR_SETTLEMENT_ALREADY_EXISTS")
    engine.release_booking(booking)
    return entity_response(booking)


@bp.post("/bookings/<booking_id>/cancel")
@endpoint("VenueAdmin")
def cancel_booking_route(booking_id):
    booking = lookups.fetch("booking", booking_id)
    if booking["status"] not in RELEASABLE:
        raise err("ERR_BOOKING_STATE_INVALID")
    if booking["hold_count"] != 0:
        raise err("ERR_HOLD_STATE_INVALID")
    engine.cancel_booking(booking)
    return entity_response(booking)


# --------------------------------------------------------------------------
# SpaceUsageRecord
# --------------------------------------------------------------------------
@bp.post("/bookings/<booking_id>/usage-records")
@endpoint("EventServicesManager")
def create_usage_record(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()
    usage_date = validate.req_date(payload, "usage_date")
    usage_kind = validate.req_enum(payload, "usage_kind", USAGE_KINDS)
    for existing in lookups.usage_records_of_booking(booking["id"]):
        if existing["usage_date"] == usage_date.isoformat():
            raise err("ERR_USAGE_RECORD_DUPLICATE")
    record = db.insert(
        "usage_record",
        {
            "booking_id": booking["id"],
            "usage_date": usage_date.isoformat(),
            "usage_kind": usage_kind,
            "recorded_by_user_id": actor(),
        },
        versioned=False,
    )
    return entity_response(record, 201)


@bp.get("/usage-records")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def list_usage_records():
    return listing(filter_rows("usage_record", {"booking_id": "booking_id"}))


@bp.get("/bookings/<booking_id>/usage-records")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def list_usage_records_of_booking(booking_id):
    booking = lookups.fetch("booking", booking_id)
    rows = lookups.usage_records_of_booking(booking["id"])
    return listing(rows, order=lambda r: (r["usage_date"], r["created_at"], r["_seq"]))
