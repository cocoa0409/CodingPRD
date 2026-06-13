"""Booking-child resources: AddOn, GuestParty, Waiver, StaffAssignment, Payment.

All nested paths validate bookingId first, then the child id (PRD section 2.7).
"""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_user_context, require_roles
from response import list_success, success
from services import booking as bk
from services import calc
from services.common import (
    as_enum, as_int, as_string, iso_from_dt, paginate, parse_iso8601,
    parse_pagination, public_view, require_body, require_present,
    stamp_create, stamp_light_create, touch,
)
from routes.bookings import guard_ownership

children_bp = Blueprint("children", __name__)

ALL_ROLES = {"VenueManager", "Coordinator", "FinanceClerk", "Guardian"}


# ============================================================================
# AddOn
# ============================================================================

REQUIRES_SKILL = {"CAKE": "COOK", "CHARACTER": "ENTERTAINER", "EXTRA_TIME": "NONE"}


@children_bp.post("/bookings/<booking_id>/add-ons")
def create_addon(booking_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    body = require_body()

    kind = as_enum(require_present(body, "kind"), "kind", {"CAKE", "CHARACTER", "EXTRA_TIME"})
    unit_price_cents = as_int(require_present(body, "unit_price_cents"), "unit_price_cents")
    if unit_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "unit_price_cents must be >= 0")
    quantity = 1
    if "quantity" in body and body["quantity"] is not None:
        quantity = as_int(body["quantity"], "quantity")
        if quantity < 1:
            raise err("ERR_INVALID_REQUEST", "quantity must be >= 1")
    extra_minutes = 0
    if "extra_minutes" in body and body["extra_minutes"] is not None:
        extra_minutes = as_int(body["extra_minutes"], "extra_minutes")
        if extra_minutes < 0:
            raise err("ERR_INVALID_REQUEST", "extra_minutes must be >= 0")

    # State gate (priority 6): only QUOTE_DRAFT / HELD admit add-on add.
    if b["status"] not in ("QUOTE_DRAFT", "HELD"):
        raise err("ERR_ADDON_LOCKED", "Add-ons are locked unless booking is QUOTE_DRAFT or HELD")

    addon = {
        "booking_id": booking_id,
        "kind": kind,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
        "extra_minutes": extra_minutes,
        "requires_skill": REQUIRES_SKILL[kind],
        "status": "ACTIVE",
    }
    stamp_create(addon)
    db.add_ons[addon["id"]] = addon

    package = db.packages[b["package_id"]]
    if kind == "EXTRA_TIME":
        # Recompute duration + window, then re-check room overlap (window grew).
        calc.recompute_window(b, package)
        bk.check_room_overlap(b)
    calc.reconcile_quote(b, package, recompute_deposit=not b["_deposit_pinned"])
    touch(b)
    return success(public_view(addon), status=201)


@children_bp.get("/bookings/<booking_id>/add-ons")
def list_addons(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    bk.get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [a for a in db.add_ons.values() if a["booking_id"] == booking_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(a) for a in page], limit, offset, total)


@children_bp.delete("/bookings/<booking_id>/add-ons/<addon_id>")
def remove_addon(booking_id, addon_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    addon = db.add_ons.get(addon_id)
    if addon is None or addon["booking_id"] != booking_id:
        raise err("ERR_ADDON_NOT_FOUND", "Add-on %s not found on this booking" % addon_id)

    # State gate (priority 6).
    if b["status"] not in ("QUOTE_DRAFT", "HELD"):
        raise err("ERR_ADDON_LOCKED", "Add-ons are locked unless booking is QUOTE_DRAFT or HELD")

    addon["status"] = "REMOVED"
    touch(addon)

    package = db.packages[b["package_id"]]
    if addon["kind"] == "EXTRA_TIME":
        # Window can only shrink; recompute and re-check (a shrunken window still fits).
        calc.recompute_window(b, package)
        bk.check_room_overlap(b)
    calc.reconcile_quote(b, package, recompute_deposit=not b["_deposit_pinned"])
    touch(b)
    return success(public_view(addon))


# ============================================================================
# GuestParty (roster events)
# ============================================================================

@children_bp.post("/bookings/<booking_id>/guest-parties")
def create_guest_party(booking_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    body = require_body()

    children_delta = 0
    if "children_delta" in body and body["children_delta"] is not None:
        children_delta = as_int(body["children_delta"], "children_delta")
    adults_delta = 0
    if "adults_delta" in body and body["adults_delta"] is not None:
        adults_delta = as_int(body["adults_delta"], "adults_delta")
    reason = "ADJUSTMENT"
    if "reason" in body and body["reason"] is not None:
        reason = as_string(body["reason"], "reason")

    new_children = b["children_count"] + children_delta
    new_adults = b["adults_count"] + adults_delta
    # children_count must remain >= 1, adults_count >= 0 (shape bounds).
    if new_children < 1:
        raise err("ERR_INVALID_REQUEST", "Resulting children_count must be >= 1")
    if new_adults < 0:
        raise err("ERR_INVALID_REQUEST", "Resulting adults_count must be >= 0")

    # Capacity re-check (priority 11).
    room = db.rooms[b["room_id"]]
    if new_children + new_adults > room["max_capacity"]:
        raise err("ERR_ROOM_CAPACITY_EXCEEDED", "Committed headcount exceeds room capacity")

    event = {
        "booking_id": booking_id,
        "children_delta": children_delta,
        "adults_delta": adults_delta,
        "reason": reason,
    }
    stamp_light_create(event)
    db.guest_parties[event["id"]] = event

    b["children_count"] = new_children
    b["adults_count"] = new_adults
    package = db.packages[b["package_id"]]
    calc.reconcile_headcount(b)
    calc.reconcile_quote(b, package, recompute_deposit=not b["_deposit_pinned"])
    touch(b)
    return success(public_view(event), status=201)


@children_bp.get("/bookings/<booking_id>/guest-parties")
def list_guest_parties(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    bk.get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [g for g in db.guest_parties.values() if g["booking_id"] == booking_id]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(g) for g in page], limit, offset, total)


# ============================================================================
# Waiver
# ============================================================================

@children_bp.post("/bookings/<booking_id>/waivers")
def create_waiver(booking_id):
    user_id, role = get_user_context()
    require_roles(role, {"Coordinator", "Guardian"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    body = require_body()

    child_name = as_string(require_present(body, "child_name"), "child_name")
    guardian_signature = None
    if "guardian_signature" in body and body["guardian_signature"] is not None:
        guardian_signature = as_string(body["guardian_signature"], "guardian_signature")

    waiver = {
        "booking_id": booking_id,
        "child_name": child_name,
        "guardian_signature": guardian_signature,
        "status": "DRAFT",
    }
    stamp_create(waiver)
    db.waivers[waiver["id"]] = waiver
    return success(public_view(waiver), status=201)


@children_bp.get("/bookings/<booking_id>/waivers")
def list_waivers(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    bk.get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [w for w in db.waivers.values() if w["booking_id"] == booking_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(w) for w in page], limit, offset, total)


@children_bp.post("/bookings/<booking_id>/waivers/<waiver_id>/sign")
def sign_waiver(booking_id, waiver_id):
    user_id, role = get_user_context()
    require_roles(role, {"Guardian", "Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    w = db.waivers.get(waiver_id)
    if w is None or w["booking_id"] != booking_id:
        raise err("ERR_WAIVER_NOT_FOUND", "Waiver %s not found on this booking" % waiver_id)
    body = require_body()

    # State gate: parent booking must be signable.
    if b["status"] not in ("HELD", "CONFIRMED", "WEATHER_HOLD", "RESCHEDULED"):
        raise err("ERR_BOOKING_NOT_SIGNABLE", "Booking is not in a signable state")
    if w["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT waiver can be signed")

    signature = require_present(body, "guardian_signature")
    if not isinstance(signature, str) or signature == "":
        raise err("ERR_INVALID_REQUEST", "guardian_signature must be non-empty")

    w["guardian_signature"] = signature
    w["status"] = "SIGNED"
    touch(w)

    calc.reconcile_headcount(b)
    touch(b)
    return success(public_view(w))


@children_bp.post("/bookings/<booking_id>/waivers/<waiver_id>/revoke")
def revoke_waiver(booking_id, waiver_id):
    user_id, role = get_user_context()
    require_roles(role, {"Guardian", "Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    guard_ownership(b, user_id, role)
    w = db.waivers.get(waiver_id)
    if w is None or w["booking_id"] != booking_id:
        raise err("ERR_WAIVER_NOT_FOUND", "Waiver %s not found on this booking" % waiver_id)

    if w["status"] != "SIGNED":
        raise err("ERR_INVALID_STATE", "Only a SIGNED waiver can be revoked")
    # A CONFIRMED booking's signed waivers are locked.
    if b["status"] == "CONFIRMED":
        raise err("ERR_WAIVER_LOCKED", "Signed waivers are locked on a CONFIRMED booking")

    w["status"] = "DRAFT"
    touch(w)

    calc.reconcile_headcount(b)
    touch(b)
    return success(public_view(w))


# ============================================================================
# StaffAssignment
# ============================================================================

@children_bp.post("/bookings/<booking_id>/staff-assignments")
def create_assignment(booking_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    body = require_body()

    staff_member_id = require_present(body, "staff_member_id")
    role_on_event = as_enum(require_present(body, "role_on_event"), "role_on_event",
                            {"HOST", "ENTERTAINER", "COOK"})

    # Priority 4: body FK resolution.
    staff = db.staff_members.get(staff_member_id)
    if staff is None:
        raise err("ERR_STAFF_NOT_FOUND", "Staff member %s not found" % staff_member_id)

    # Priority 7: config preconditions.
    if staff["status"] != "AVAILABLE":
        raise err("ERR_STAFF_INACTIVE", "Staff member is INACTIVE")
    if role_on_event not in staff["skills"]:
        raise err("ERR_SKILL_MISMATCH", "role_on_event not present in staff skills")

    # Priority 10: staff window overlap (closed intervals).
    bk.check_staff_overlap(staff_member_id, b)

    assignment = {
        "booking_id": booking_id,
        "staff_member_id": staff_member_id,
        "role_on_event": role_on_event,
        "status": "ASSIGNED",
    }
    stamp_create(assignment)
    db.staff_assignments[assignment["id"]] = assignment
    return success(public_view(assignment), status=201)


@children_bp.get("/bookings/<booking_id>/staff-assignments")
def list_assignments(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    bk.get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [a for a in db.staff_assignments.values() if a["booking_id"] == booking_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(a) for a in page], limit, offset, total)


@children_bp.post("/bookings/<booking_id>/staff-assignments/<assignment_id>/release")
def release_assignment(booking_id, assignment_id):
    _, role = get_user_context()
    require_roles(role, {"Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    a = db.staff_assignments.get(assignment_id)
    if a is None or a["booking_id"] != booking_id:
        raise err("ERR_ASSIGNMENT_NOT_FOUND", "Assignment %s not found on this booking" % assignment_id)

    if a["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Only an ASSIGNED assignment can be released")

    # A CONFIRMED booking must keep exactly one HOST; releasing the sole HOST is blocked.
    if b["status"] == "CONFIRMED" and a["role_on_event"] == "HOST":
        hosts = bk.assigned_hosts(booking_id)
        if len(hosts) <= 1:
            raise err("ERR_HOST_REQUIRED", "Cannot release the sole HOST of a CONFIRMED booking")

    a["status"] = "RELEASED"
    touch(a)
    return success(public_view(a))


@children_bp.get("/staff-members/<staff_id>/staff-assignments")
def list_assignments_for_staff(staff_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    if staff_id not in db.staff_members:
        raise err("ERR_STAFF_NOT_FOUND", "Staff member %s not found" % staff_id)
    limit, offset = parse_pagination()
    items = [a for a in db.staff_assignments.values() if a["staff_member_id"] == staff_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(a) for a in page], limit, offset, total)


# ============================================================================
# Payment
# ============================================================================

@children_bp.post("/bookings/<booking_id>/payments")
def create_payment(booking_id):
    _, role = get_user_context()
    require_roles(role, {"FinanceClerk", "Coordinator"})
    b = bk.get_booking_or_404(booking_id)
    body = require_body()

    direction = as_enum(require_present(body, "direction"), "direction", {"CHARGE", "REFUND"})
    amount_cents = as_int(require_present(body, "amount_cents"), "amount_cents")
    if amount_cents < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be >= 1")
    purpose = "BALANCE"
    if "purpose" in body and body["purpose"] is not None:
        purpose = as_enum(body["purpose"], "purpose",
                          {"DEPOSIT", "BALANCE", "CANCELLATION_REFUND"})

    # Priority 13: a manual REFUND may not exceed amount currently paid.
    if direction == "REFUND" and amount_cents > b["amount_paid_cents"]:
        raise err("ERR_REFUND_EXCEEDS_PAID", "Refund exceeds amount paid")

    payment = {
        "booking_id": booking_id,
        "direction": direction,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "status": "SETTLED",
    }
    stamp_create(payment)
    db.payments[payment["id"]] = payment

    calc.reconcile_balance(b)
    touch(b)
    return success(public_view(payment), status=201)


@children_bp.get("/bookings/<booking_id>/payments")
def list_payments(booking_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    bk.get_booking_or_404(booking_id)
    limit, offset = parse_pagination()
    items = [p for p in db.payments.values() if p["booking_id"] == booking_id]
    direction = request.args.get("direction")
    if direction is not None:
        items = [p for p in items if p["direction"] == direction]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(p) for p in page], limit, offset, total)


@children_bp.post("/bookings/<booking_id>/payments/<payment_id>/void")
def void_payment(booking_id, payment_id):
    _, role = get_user_context()
    require_roles(role, {"FinanceClerk"})
    b = bk.get_booking_or_404(booking_id)
    p = db.payments.get(payment_id)
    if p is None or p["booking_id"] != booking_id:
        raise err("ERR_PAYMENT_NOT_FOUND", "Payment %s not found on this booking" % payment_id)

    # State gates (priority 6): not on a COMPLETED booking; refunds are immutable.
    if b["status"] == "COMPLETED":
        raise err("ERR_BOOKING_SETTLED", "Cannot void a payment on a COMPLETED booking")
    if p["direction"] == "REFUND":
        raise err("ERR_REFUND_IMMUTABLE", "Refund payments are immutable")
    if p["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Only a SETTLED payment can be voided")

    p["status"] = "VOIDED"
    touch(p)

    calc.reconcile_balance(b)
    touch(b)
    return success(public_view(p))
