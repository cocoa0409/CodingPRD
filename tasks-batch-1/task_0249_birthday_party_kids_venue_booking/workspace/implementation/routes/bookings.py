"""Booking core endpoints: create, list, get, headcount patch, and lifecycle
transitions (hold, release-hold, confirm, weather-hold, reschedule, complete, cancel).
"""

from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err
from middleware import get_user_context, require_roles
from response import list_success, success
from services import booking as bk
from services import calc
from services.common import (
    as_int, iso_from_dt, paginate, parse_iso8601, parse_pagination,
    public_view, require_body, require_present, stamp_create, touch,
)

bookings_bp = Blueprint("bookings", __name__)

ALL_ROLES = {"VenueManager", "Coordinator", "FinanceClerk", "Guardian"}


# ----------------------------------------------------------------------------
# Guardian ownership guard (PRD section 2.1): for booking-scoped writes a Guardian
# may act only on their own booking (guardian_user_id == X-User-ID).
# ----------------------------------------------------------------------------

def guard_ownership(booking, user_id, role):
    if role == "Guardian" and booking.get("guardian_user_id") != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Guardian may only act on their own booking")


# ============================================================================
# Create / list / get
# ============================================================================

@bookings_bp.post("/bookings")
def create_booking():
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    body = require_body()

    room_id = require_present(body, "room_id")
    package_id = require_present(body, "package_id")
    event_start_raw = require_present(body, "event_start_utc")
    children_count = as_int(require_present(body, "children_count"), "children_count")
    if children_count < 1:
        raise err("ERR_INVALID_REQUEST", "children_count must be >= 1")
    adults_count = 0
    if "adults_count" in body and body["adults_count"] is not None:
        adults_count = as_int(body["adults_count"], "adults_count")
        if adults_count < 0:
            raise err("ERR_INVALID_REQUEST", "adults_count must be >= 0")
    event_start = parse_iso8601(event_start_raw, "event_start_utc")

    # Priority 4: body FK resolution.
    room = db.rooms.get(room_id)
    if room is None:
        raise err("ERR_ROOM_NOT_FOUND", "Room %s not found" % room_id)
    package = db.packages.get(package_id)
    if package is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Package %s not found" % package_id)
    if room["venue_id"] != package["venue_id"]:
        raise err("ERR_VENUE_MISMATCH", "Room and package belong to different venues")

    # Priority 7 (cross-entity config precondition): a RETIRED package rejects new
    # quotes (PRD 3.1). Opening a booking lands it in QUOTE_DRAFT and computes the
    # quote estimate immediately (PRD 3.2), so a booking create is a "new quote".
    if package["status"] != "LISTED":
        raise err("ERR_PACKAGE_RETIRED", "Package is RETIRED and rejects new quotes")

    venue = db.venues[room["venue_id"]]

    booking = {
        "venue_id": room["venue_id"],
        "room_id": room_id,
        "package_id": package_id,
        "guardian_user_id": user_id if role == "Guardian" else body.get("guardian_user_id"),
        "event_start_utc": iso_from_dt(event_start),
        "children_count": children_count,
        "adults_count": adults_count,
        "reschedule_count": 0,
        "amount_paid_cents": 0,
        "final_total_cents": 0,
        "deposit_due_cents": 0,
        "status": "QUOTE_DRAFT",
        "_deposit_pinned": False,
    }
    stamp_create(booking)

    # effective_duration / event_end
    booking["effective_duration_minutes"] = package["base_duration_minutes"]
    end = event_start + timedelta(minutes=booking["effective_duration_minutes"])
    booking["event_end_utc"] = iso_from_dt(end)

    # headcount-derived
    calc.reconcile_headcount(booking)
    # weather eligibility
    booking["weather_eligible"] = (room["room_kind"] == "OUTDOOR"
                                   and venue["weather_dependent"] is True)
    # quote estimate + deposit + balance + payment_status
    calc.reconcile_quote(booking, package, recompute_deposit=True)

    db.bookings[booking["id"]] = booking
    return success(public_view(booking), status=201)


@bookings_bp.get("/bookings")
def list_bookings():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.bookings.values())
    for field in ("room_id", "package_id", "venue_id", "guardian_user_id",
                  "status", "payment_status"):
        val = request.args.get(field)
        if val is not None:
            items = [b for b in items if b.get(field) == val]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(b) for b in page], limit, offset, total)


@bookings_bp.get("/bookings/<booking_id>")
def get_booking(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    b = bk.get_booking_or_404(booking_id)
    return success(public_view(b))


# ============================================================================
# PATCH headcount
# ============================================================================

@bookings_bp.patch("/bookings/<booking_id>")
def patch_headcount(booking_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    body = require_body()

    # State gate (priority 6): only QUOTE_DRAFT / HELD admit headcount edits.
    if b["status"] not in ("QUOTE_DRAFT", "HELD"):
        raise err("ERR_INVALID_STATE", "Headcount can only change while QUOTE_DRAFT or HELD")

    new_children = b["children_count"]
    new_adults = b["adults_count"]
    if "children_count" in body and body["children_count"] is not None:
        new_children = as_int(body["children_count"], "children_count")
        if new_children < 1:
            raise err("ERR_INVALID_REQUEST", "children_count must be >= 1")
    if "adults_count" in body and body["adults_count"] is not None:
        new_adults = as_int(body["adults_count"], "adults_count")
        if new_adults < 0:
            raise err("ERR_INVALID_REQUEST", "adults_count must be >= 0")

    # Capacity re-check (priority 11).
    room = db.rooms[b["room_id"]]
    if new_children + new_adults > room["max_capacity"]:
        raise err("ERR_ROOM_CAPACITY_EXCEEDED",
                  "children + adults exceeds room max_capacity")

    b["children_count"] = new_children
    b["adults_count"] = new_adults
    package = db.packages[b["package_id"]]
    calc.reconcile_headcount(b)
    calc.reconcile_quote(b, package, recompute_deposit=not b["_deposit_pinned"])
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: hold
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/hold")
def hold_booking(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)

    if b["status"] != "QUOTE_DRAFT":
        raise err("ERR_INVALID_STATE", "Only a QUOTE_DRAFT booking can be held")

    room = db.rooms[b["room_id"]]
    package = db.packages[b["package_id"]]

    # Priority 7: config preconditions.
    if room["status"] != "OPEN":
        raise err("ERR_ROOM_CLOSED", "Room is CLOSED")
    if package["status"] != "LISTED":
        raise err("ERR_PACKAGE_RETIRED", "Package is RETIRED")

    # Priority 10: room window overlap (with the candidate not yet active).
    bk.check_room_overlap(b)

    # Priority 11: capacity.
    if b["children_count"] + b["adults_count"] > room["max_capacity"]:
        raise err("ERR_ROOM_CAPACITY_EXCEEDED", "Committed headcount exceeds room capacity")

    b["status"] = "HELD"
    calc.reconcile_quote(b, package, recompute_deposit=True)
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: release-hold
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/release-hold")
def release_hold(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)

    if b["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Only a HELD booking can be released")
    if b["payment_status"] != "UNPAID":
        raise err("ERR_HOLD_HAS_PAYMENTS", "Cannot release a hold with payments taken")

    b["status"] = "QUOTE_DRAFT"
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: confirm (HELD->CONFIRMED and RESCHEDULED->CONFIRMED)
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)

    if b["status"] not in ("HELD", "RESCHEDULED"):
        raise err("ERR_INVALID_STATE", "Only a HELD or RESCHEDULED booking can be confirmed")

    from_held = b["status"] == "HELD"

    # Priority 8: waiver completeness.
    if b["waivers_signed"] < b["waivers_required"]:
        raise err("ERR_WAIVERS_INCOMPLETE", "Not all required waivers are signed")
    # Priority 9: staffing completeness (masks the priority-13 fiscal gate, per PRD 2.8:
    # "Earlier checks mask later ones") — HELD->CONFIRMED checks host + add-on staffing;
    # RESCHEDULED->CONFIRMED checks the host requirement only.
    if from_held:
        bk.check_staffing_complete(b)
    else:
        hosts = bk.assigned_hosts(b["id"])
        if len(hosts) != 1:
            raise err("ERR_HOST_NOT_ASSIGNED", "Exactly one ASSIGNED HOST is required to confirm")
    # Priority 13: deposit gate (after staffing completeness).
    if b["amount_paid_cents"] < b["deposit_due_cents"]:
        raise err("ERR_DEPOSIT_NOT_MET", "Deposit has not been met")

    b["status"] = "CONFIRMED"
    if from_held:
        b["_deposit_pinned"] = True  # pin deposit; no longer recomputed
    calc.reconcile_balance(b)
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: weather-hold
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/weather-hold")
def weather_hold(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)

    if b["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED booking can be weather-held")
    # Priority 12 timing/eligibility.
    if not b["weather_eligible"]:
        raise err("ERR_NOT_WEATHER_ELIGIBLE", "Booking is not weather-eligible")
    start = parse_iso8601(b["event_start_utc"], "event_start_utc")
    if bk.clock_now() >= start:
        raise err("ERR_EVENT_ALREADY_STARTED", "Event has already started")

    b["status"] = "WEATHER_HOLD"
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: reschedule (WEATHER_HOLD->RESCHEDULED, OCC-guarded)
# ============================================================================

@bookings_bp.patch("/bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    body = require_body()

    new_start_raw = require_present(body, "event_start_utc")
    expected_version = require_present(body, "expected_booking_version")
    expected_version = as_int(expected_version, "expected_booking_version")
    new_start = parse_iso8601(new_start_raw, "event_start_utc")

    # State gate (priority 6).
    if b["status"] != "WEATHER_HOLD":
        raise err("ERR_INVALID_STATE", "Only a WEATHER_HOLD booking can be rescheduled")

    # Priority 10: new-window overlap (other active bookings; self excluded).
    bk.check_room_overlap(b, start_override=new_start)

    # Priority 14: OCC version check.
    if expected_version != b["version"]:
        raise err("ERR_STALE_VERSION", "expected_booking_version does not match")

    b["event_start_utc"] = iso_from_dt(new_start)
    end = new_start + timedelta(minutes=b["effective_duration_minutes"])
    b["event_end_utc"] = iso_from_dt(end)
    b["reschedule_count"] += 1
    b["status"] = "RESCHEDULED"
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: complete (CONFIRMED->COMPLETED, settlement)
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)

    if b["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED booking can be completed")

    # Priority 12: event must have ended.
    end = parse_iso8601(b["event_end_utc"], "event_end_utc")
    if bk.clock_now() < end:
        raise err("ERR_EVENT_NOT_ENDED", "Event has not yet ended")

    package = db.packages[b["package_id"]]
    # Compute settlement and balance against it BEFORE the fiscal gate.
    final_total = calc.compute_final_total(b, package)
    # The balance gate compares amount_paid against the settlement total.
    if final_total - b["amount_paid_cents"] > 0:
        raise err("ERR_BALANCE_OUTSTANDING", "Outstanding balance against final total")

    b["final_total_cents"] = final_total
    b["status"] = "COMPLETED"
    calc.reconcile_balance(b)  # now uses final_total since COMPLETED
    bk.release_all_staff(b["id"])
    touch(b)
    return success(public_view(b))


# ============================================================================
# Lifecycle: cancel (any non-terminal -> CANCELLED)
# ============================================================================

@bookings_bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)

    if b["status"] not in ("QUOTE_DRAFT", "HELD", "CONFIRMED", "WEATHER_HOLD", "RESCHEDULED"):
        raise err("ERR_INVALID_STATE", "Booking is not in a cancellable state")

    # Timing gate (priority 12): allowed if before event start OR pre-confirmation.
    start = parse_iso8601(b["event_start_utc"], "event_start_utc")
    if not (bk.clock_now() < start or b["status"] in ("QUOTE_DRAFT", "HELD")):
        raise err("ERR_EVENT_ALREADY_STARTED", "Event already started; cannot cancel")

    prior_status = b["status"]
    b["status"] = "CANCELLED"

    # Cascade across children.
    bk.cascade_cancel(b)

    # Synthesize a tiered refund if money was paid.
    if b["amount_paid_cents"] > 0:
        refund_amount = bk.cancellation_refund_amount(b, prior_status)
        if refund_amount > 0:
            payment = {
                "booking_id": b["id"],
                "direction": "REFUND",
                "amount_cents": refund_amount,
                "purpose": "CANCELLATION_REFUND",
                "status": "SETTLED",
            }
            stamp_create(payment)
            db.payments[payment["id"]] = payment

    calc.reconcile_balance(b)
    touch(b)
    return success(public_view(b))
