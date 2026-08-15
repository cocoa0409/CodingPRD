"""Event booking endpoints (PRD 3.9)."""
from flask import Blueprint, request

import db
from db import parse_iso
from errors import (
    err_invalid_state, err_posture_blocks, err_invalid_time_range,
    err_event_pool, err_staffing,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascade import event_surge_on_activate, event_surge_on_complete
from services.common import (
    body, require_string, require_int, optional_int, optional_enum,
    require_datetime, optional_list, parse_pagination, paginate,
    require_ref, get_event, public_view,
)
from services.fees import event_pool_charge, compute_cancellation_fee

bp = Blueprint("events", __name__)

POLICIES = {"FORFEIT_DEPOSIT", "SLIDING_NOTICE"}


def _check_posture_allows_event(facility):
    if facility["posture"] in ("CLOSED_TEMPORARY", "DECOMMISSIONED"):
        raise err_posture_blocks()


@bp.post("/ops/event-bookings")
def create_event():
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    name = require_string(payload, "event_name")
    start_at = require_datetime(payload, "start_at")
    end_at = require_datetime(payload, "end_at")
    presale = require_int(payload, "presale_allocation", minimum=0)
    min_staff = require_int(payload, "min_staff", minimum=0)
    deposit = optional_int(payload, "deposit_cents", default=0, minimum=0)
    policy = optional_enum(payload, "cancellation_policy", POLICIES, default="FORFEIT_DEPOSIT")
    if end_at <= start_at:
        raise err_invalid_time_range()
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "event_name": name,
        "booking_status": "REQUESTED",
        "start_at": db.format_iso(start_at),
        "end_at": db.format_iso(end_at),
        "presale_allocation": presale,
        "min_staff": min_staff,
        "staffing_assignments": [],
        "deposit_cents": deposit,
        "cancellation_policy": policy,
        "cancellation_fee_cents": None,
        "deposit_refund_cents": None,
    }
    db.stamp_new(ent)
    db.event_bookings[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/event-bookings/<event_booking_id>")
def get_event_route(event_booking_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_event(event_booking_id)))


@bp.get("/ops/event-bookings")
def list_events():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.event_bookings.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("booking_status")
    if facility_id is not None:
        items = [e for e in items if e["facility_id"] == facility_id]
    if status is not None:
        items = [e for e in items if e["booking_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(e) for e in page], limit, offset, total)


@bp.post("/ops/event-bookings/<event_booking_id>/confirm")
def confirm_event(event_booking_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ev = get_event(event_booking_id)
    payload = body()
    roster = optional_list(payload, "staffing_assignments")
    if roster is None:
        from errors import err_validation
        raise err_validation("missing required field: staffing_assignments")
    if ev["booking_status"] != "REQUESTED":
        raise err_invalid_state("only a REQUESTED booking may be confirmed")
    facility = db.facilities[ev["facility_id"]]
    _check_posture_allows_event(facility)
    # PRD 3.9: capacity first, then staffing
    if event_pool_charge(ev, facility["id"]) > facility["event_pool_spaces"]:
        raise err_event_pool()
    if len(roster) < ev["min_staff"]:
        raise err_staffing()
    ev["booking_status"] = "CONFIRMED"
    ev["staffing_assignments"] = roster
    db.touch(ev)
    return success_object(public_view(ev))


@bp.post("/ops/event-bookings/<event_booking_id>/activate")
def activate_event(event_booking_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ev = get_event(event_booking_id)
    if ev["booking_status"] != "CONFIRMED":
        raise err_invalid_state("only a CONFIRMED booking may be activated")
    facility = db.facilities[ev["facility_id"]]
    _check_posture_allows_event(facility)
    now = db.now_dt()
    if not (parse_iso(ev["start_at"]) <= now < parse_iso(ev["end_at"])):
        raise err_invalid_time_range("activation requires logical now within [start_at, end_at)")
    ev["booking_status"] = "ACTIVE"
    db.touch(ev)
    event_surge_on_activate(facility)
    return success_object(public_view(ev))


@bp.post("/ops/event-bookings/<event_booking_id>/complete")
def complete_event(event_booking_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ev = get_event(event_booking_id)
    if ev["booking_status"] != "ACTIVE":
        raise err_invalid_state("only an ACTIVE booking may be completed")
    ev["booking_status"] = "COMPLETED"
    db.touch(ev)
    facility = db.facilities[ev["facility_id"]]
    event_surge_on_complete(facility, ev)
    return success_object(public_view(ev))


@bp.post("/ops/event-bookings/<event_booking_id>/cancel")
def cancel_event(event_booking_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ev = get_event(event_booking_id)
    payload = body()
    require_string(payload, "reason")
    if ev["booking_status"] not in ("REQUESTED", "CONFIRMED"):
        raise err_invalid_state("only a REQUESTED or CONFIRMED booking may be cancelled")
    fee, refund = compute_cancellation_fee(ev, db.now_dt())
    ev["booking_status"] = "CANCELLED"
    ev["cancellation_fee_cents"] = fee
    ev["deposit_refund_cents"] = refund
    db.touch(ev)
    return success_object(public_view(ev))
