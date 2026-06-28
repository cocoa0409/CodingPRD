"""Booking routes: create, list, get, confirm, complete, cancel, reschedule,
add-ons, no-show-events (PRD §3.3, §3.4, §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_LOCATION_MISMATCH, ERR_INVALID_STATE,
    ERR_MEMBER_SUSPENDED, ERR_INTRO_REQUIRED, ERR_LOCATION_CLOSED,
    ERR_ADDON_NOT_ALLOWED, ERR_VALIDATION,
)
from middleware import authenticate, require_role, forbid
from response import success, success_list
from util import (
    get_json_body, require_str, require_enum, require_int, opt_str, opt_int,
    parse_pagination, paginate, parse_iso, now_clock,
)
from services.common import make_full, make_lean, bump
from services.calc import no_show_fee_late_cancel, intro_assessment_composite
from services.wallet import reconcile_creditpack_status
from services.strikes import create_no_show_event
from services import serialize
from services.booking import (
    _resolve_wallet, validate_booking_slot, build_booking, void_addons,
    release_credit, forfeit_credit, consume_credit, NON_TERMINAL_SCHEDULE,
)

bp = Blueprint("bookings", __name__)

MEMBER_ROLES = ["StudioManager", "FrontDesk", "Member"]
ALL_ROLES = ["StudioManager", "FrontDesk", "Member", "Flexologist"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.route("/bookings", methods=["POST"])
def create_booking():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    body = get_json_body()
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    service_id = require_str(body, "service_id")
    flexologist_id = require_str(body, "flexologist_id")
    table_id = require_str(body, "table_id")
    session_start = require_str(body, "session_start_utc")
    funding_source = require_enum(body, "funding_source", {"MEMBERSHIP", "CREDIT_PACK"})
    funding_id = require_str(body, "funding_id")
    start = parse_iso(session_start)

    # priority 2: ownership (member acts only on own member_id).
    if p.is_member and p.user_id != member_id:
        forbid()

    # priority 3: existence, validated left-to-right.
    member = store.members.get(member_id)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    location = store.locations.get(location_id)
    if location is None:
        raise err(ERR_NOT_FOUND, "Location not found.")
    service = store.services.get(service_id)
    if service is None:
        raise err(ERR_NOT_FOUND, "Service not found.")
    flexologist = store.flexologists.get(flexologist_id)
    if flexologist is None:
        raise err(ERR_NOT_FOUND, "Flexologist not found.")
    table = store.tables.get(table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "Table not found.")
    wallet = _resolve_wallet(funding_source, funding_id)
    if wallet is None:
        raise err(ERR_NOT_FOUND, "Funding wallet not found.")

    # priority 4: cross-location integrity + funding_id type vs funding_source.
    _check_location_integrity(location_id, service, flexologist, table, wallet)

    # ERR_LOCATION_CLOSED: a booking at a CLOSED location is rejected (PRD §3.3).
    if location["status"] == "CLOSED":
        raise err(ERR_LOCATION_CLOSED, "Location is closed to new bookings.")

    # priority 7: member standing.
    if member["status"] == "SUSPENDED":
        raise err(ERR_MEMBER_SUSPENDED, "Member is suspended.")

    # priority 8: intro gate.
    if not member["intro_completed"] and service["kind"] != "INTRO":
        raise err(ERR_INTRO_REQUIRED, "Member must complete intro before booking non-intro services.")

    # priorities 9-13: temporal/resource/certification/credit gauntlet.
    end = start + timedelta(minutes=service["duration_minutes"])
    validate_booking_slot(member, location, service, flexologist, table,
                          funding_source, wallet, start, end)

    rec = build_booking(member, location, service, flexologist, table,
                        funding_source, wallet, start)
    return success(serialize.booking_view(rec), 201)


def _check_location_integrity(location_id, service, flexologist, table, wallet):
    if (service["location_id"] != location_id
            or flexologist["location_id"] != location_id
            or table["location_id"] != location_id
            or wallet["location_id"] != location_id):
        raise err(ERR_LOCATION_MISMATCH, "Referenced resource belongs to a different location.")


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------
@bp.route("/bookings", methods=["GET"])
def list_bookings():
    p = authenticate()
    require_role(p, ALL_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "member_id": _qs("member_id"),
        "location_id": _qs("location_id"),
        "service_id": _qs("service_id"),
        "flexologist_id": _qs("flexologist_id"),
        "table_id": _qs("table_id"),
        "series_id": _qs("series_id"),
        "rescheduled_from_booking_id": _qs("rescheduled_from_booking_id"),
        "funding_id": _qs("funding_id"),
        "schedule_status": _qs("schedule_status"),
        "credit_status": _qs("credit_status"),
    }
    items = []
    for b in store.bookings.values():
        if all(v is None or b.get(k) == v for k, v in filters.items()):
            items.append(b)
    if p.is_member:
        items = [b for b in items if b["member_id"] == p.user_id]
    elif p.is_flexologist:
        items = [b for b in items if b["flexologist_id"] == p.user_id]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.booking_view(b) for b in window], limit, offset, total)


@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    if p.is_flexologist and p.user_id != rec["flexologist_id"]:
        forbid()
    return success(serialize.booking_view(rec), 200)


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------
@bp.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    # state precondition (priority 5) precedes member-suspended (priority 7).
    if rec["schedule_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Booking is not REQUESTED.")
    member = store.members.get(rec["member_id"])
    if member and member["status"] == "SUSPENDED":
        raise err(ERR_MEMBER_SUSPENDED, "Member is suspended.")
    location = store.locations.get(rec["location_id"])
    if location and location["status"] == "CLOSED":
        raise err(ERR_LOCATION_CLOSED, "Location is closed.")
    rec["schedule_status"] = "CONFIRMED"
    bump(rec)
    return success(serialize.booking_view(rec), 200)


# ---------------------------------------------------------------------------
# Complete (+ INTRO assessment)
# ---------------------------------------------------------------------------
@bp.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    p = authenticate()
    require_role(p, ["StudioManager", "Flexologist"])
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_flexologist and p.user_id != rec["flexologist_id"]:
        forbid()
    body = get_json_body()

    # preconditions: CONFIRMED, clock >= session_start_utc, credit_status==HELD.
    if rec["schedule_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Booking is not CONFIRMED.")
    if not (now_clock() >= parse_iso(rec["session_start_utc"])):
        raise err(ERR_INVALID_STATE, "Clock has not reached session_start_utc.")
    if rec["credit_status"] != "HELD":
        raise err(ERR_INVALID_STATE, "Booking credit is not HELD.")

    rec["schedule_status"] = "COMPLETED"
    consume_credit(rec)

    # INTRO completion: flip intro_completed and set mobility_tier from assessment.
    if rec["is_intro"]:
        shoulder = _assessment_score(body, "assessment_shoulder")
        hip = _assessment_score(body, "assessment_hip")
        spine = _assessment_score(body, "assessment_spine")
        ankle = _assessment_score(body, "assessment_ankle")
        _composite, tier = intro_assessment_composite(shoulder, hip, spine, ankle)
        member = store.members.get(rec["member_id"])
        if member is not None:
            member["intro_completed"] = True
            member["mobility_tier"] = tier
            bump(member)
    bump(rec)
    return success(serialize.booking_view(rec), 200)


def _assessment_score(body, name):
    v = body.get(name, 0)
    if v is None:
        v = 0
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_VALIDATION, f"{name} must be a number 0..100.")
    if v < 0 or v > 100:
        raise err(ERR_VALIDATION, f"{name} must be between 0 and 100.")
    return v


# ---------------------------------------------------------------------------
# Cancel (free vs late)
# ---------------------------------------------------------------------------
@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    if rec["schedule_status"] not in NON_TERMINAL_SCHEDULE:
        raise err(ERR_INVALID_STATE, "Booking cannot be cancelled from its current state.")
    _do_cancel(rec)
    bump(rec)
    return success(serialize.booking_view(rec), 200)


def _do_cancel(rec):
    """Resolve free CANCELLED vs LATE_CANCELLED by clock vs cancel window (PRD §3.5)."""
    location = store.locations.get(rec["location_id"])
    clock = now_clock()
    start = parse_iso(rec["session_start_utc"])
    window_edge = start - timedelta(hours=location["cancel_window_hours"])
    if clock <= window_edge:
        # free cancel
        rec["schedule_status"] = "CANCELLED"
        release_credit(rec)
        rec["fee_charged_cents"] = 0
        void_addons(rec["id"])
    else:
        # late cancel (clock strictly after edge and before start; state guard
        # already ensures non-terminal — at/after start is still treated late here)
        rec["schedule_status"] = "LATE_CANCELLED"
        forfeit_credit(rec)
        rec["fee_charged_cents"] = no_show_fee_late_cancel(
            rec["list_price_cents"], location["late_cancel_pct"])
        void_addons(rec["id"])
        create_no_show_event(rec["member_id"], rec["id"], "LATE_CANCEL")


# ---------------------------------------------------------------------------
# Reschedule (cancel-and-recreate)
# ---------------------------------------------------------------------------
@bp.route("/bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    body = get_json_body()
    new_start_str = require_str(body, "session_start_utc")
    new_start = parse_iso(new_start_str)
    new_flex_id = opt_str(body, "flexologist_id", rec["flexologist_id"])
    new_table_id = opt_str(body, "table_id", rec["table_id"])

    if rec["schedule_status"] not in NON_TERMINAL_SCHEDULE:
        raise err(ERR_INVALID_STATE, "Only a non-terminal booking can be rescheduled.")

    member = store.members.get(rec["member_id"])
    location = store.locations.get(rec["location_id"])
    service = store.services.get(rec["service_id"])
    flexologist = store.flexologists.get(new_flex_id)
    if flexologist is None:
        raise err(ERR_NOT_FOUND, "Flexologist not found.")
    table = store.tables.get(new_table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "Table not found.")
    wallet = _resolve_wallet(rec["funding_source"], rec["funding_id"])
    if wallet is None:
        raise err(ERR_NOT_FOUND, "Funding wallet not found.")

    # cross-location integrity for the new resources.
    _check_location_integrity(rec["location_id"], service, flexologist, table, wallet)
    if location["status"] == "CLOSED":
        raise err(ERR_LOCATION_CLOSED, "Location is closed to new bookings.")
    if member["status"] == "SUSPENDED":
        raise err(ERR_MEMBER_SUSPENDED, "Member is suspended.")

    end = new_start + timedelta(minutes=service["duration_minutes"])
    # Validate the replacement slot BEFORE disturbing the predecessor. The
    # predecessor still holds its credit/resources, so exclude it from overlap
    # and credit checks (it is about to be released free of charge).
    _validate_excluding(rec, member, location, service, flexologist, table,
                        wallet, new_start, end)

    # Cancel predecessor free of charge.
    rec["schedule_status"] = "CANCELLED"
    release_credit(rec)
    rec["fee_charged_cents"] = 0
    void_addons(rec["id"])
    bump(rec)

    # Create replacement (REQUESTED/HELD), linked to predecessor.
    replacement = build_booking(member, location, service, flexologist, table,
                                rec["funding_source"], wallet, new_start,
                                rescheduled_from_booking_id=rec["id"])
    return success(serialize.booking_view(replacement), 201)


def _validate_excluding(predecessor, member, location, service, flexologist,
                        table, wallet, start, end):
    """Run the slot gauntlet for the replacement, excluding the predecessor
    from overlap so its soon-to-be-released slot doesn't self-conflict, and
    accounting for its soon-to-be-released credit."""
    from services.booking import (
        _overlapping_table_bookings, _flexologist_conflict,
    )
    from util import minute_of_day
    from services.wallet import wallet_available
    from errors import (
        ERR_OUTSIDE_BUSINESS_HOURS, ERR_TABLE_UNAVAILABLE,
        ERR_FLEXOLOGIST_UNAVAILABLE, ERR_FLEXOLOGIST_NOT_CERTIFIED,
        ERR_INSUFFICIENT_CREDITS,
    )
    clock = now_clock()
    if not (start > clock):
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "session_start_utc must be in the future.")
    start_mod = minute_of_day(start)
    if not (location["open_minute_of_day"] <= start_mod < location["close_minute_of_day"]):
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "session_start_utc outside business hours.")
    if service["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Service is not bookable.")
    if flexologist["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Flexologist is not bookable.")
    if table["status"] != "ACTIVE":
        raise err(ERR_OUTSIDE_BUSINESS_HOURS, "Table is not bookable.")
    if _overlapping_table_bookings(table["id"], start, end, exclude_id=predecessor["id"]):
        raise err(ERR_TABLE_UNAVAILABLE, "Table already booked for an overlapping interval.")
    if _flexologist_conflict(flexologist["id"], start, end,
                             location["flexologist_buffer_minutes"],
                             exclude_id=predecessor["id"]):
        raise err(ERR_FLEXOLOGIST_UNAVAILABLE, "Flexologist unavailable within buffer window.")
    if service["kind"] == "INTRO" and not flexologist.get("certified_intro", False):
        raise err(ERR_FLEXOLOGIST_NOT_CERTIFIED, "Flexologist is not certified for intro sessions.")
    if predecessor["funding_source"] == "CREDIT_PACK":
        if wallet["status"] == "EXPIRED":
            raise err(ERR_INSUFFICIENT_CREDITS, "Credit pack is expired.")
        if start >= parse_iso(wallet["expires_utc"]):
            raise err(ERR_INSUFFICIENT_CREDITS, "session_start_utc at/after credit pack expiry.")
    # The predecessor's held credit will be released, so it is available to the
    # replacement. Add it back when it funds the same wallet.
    available = wallet_available(predecessor["funding_source"], wallet)
    if (predecessor["funding_id"] == wallet["id"]
            and predecessor["credit_status"] == "HELD"):
        available += predecessor["credit_cost"]
    if available < service["credit_cost"]:
        raise err(ERR_INSUFFICIENT_CREDITS, "Funding wallet has insufficient available credits.")


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
@bp.route("/bookings/<bid>/add-ons", methods=["POST"])
def create_addon(bid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    body = get_json_body()
    kind = require_enum(body, "kind", {"COMPRESSION", "PERCUSSION"})
    price = require_int(body, "price_cents", minimum=0)
    if rec["schedule_status"] not in NON_TERMINAL_SCHEDULE:
        raise err(ERR_ADDON_NOT_ALLOWED, "Add-on can only attach to a REQUESTED/CONFIRMED booking.")
    addon = make_lean({
        "booking_id": bid,
        "kind": kind,
        "price_cents": price,
        "voided": False,
    })
    store.add_ons[addon["id"]] = addon
    return success(serialize.addon_view(addon), 201)


@bp.route("/bookings/<bid>/add-ons", methods=["GET"])
def list_addons(bid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    if p.is_flexologist and p.user_id != rec["flexologist_id"]:
        forbid()
    limit, offset = parse_pagination()
    items = [a for a in store.add_ons.values() if a["booking_id"] == bid]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.addon_view(a) for a in window], limit, offset, total)


@bp.route("/bookings/<bid>/no-show-events", methods=["GET"])
def booking_no_show_events(bid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    limit, offset = parse_pagination()
    items = [e for e in store.no_show_events.values() if e["booking_id"] == bid]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.noshow_view(e) for e in window], limit, offset, total)


def _qs(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
