"""Path-existence resolution and ownership checks (PRD §2.7, §2.8, §2.1).

Path identifiers are resolved left-to-right and the first that does not resolve
raises ERR_NOT_FOUND (404). Body foreign keys raise ERR_REFERENCE_NOT_FOUND
(404). Ownership for entity-backed roles raises ERR_FORBIDDEN (403).
"""

from flask import g

import errors
from db import db


# --- Path-existence resolution (ERR_NOT_FOUND, 404) -----------------------

def get_location_or_404(location_id):
    loc = db.locations.get(location_id)
    if loc is None:
        raise errors.not_found("Location not found")
    return loc


def get_service_type_or_404(service_type_id):
    st = db.service_types.get(service_type_id)
    if st is None:
        raise errors.not_found("ServiceType not found")
    return st


def get_room_or_404(room_id):
    room = db.rooms.get(room_id)
    if room is None:
        raise errors.not_found("Room not found")
    return room


def get_technician_or_404(technician_id):
    tech = db.technicians.get(technician_id)
    if tech is None:
        raise errors.not_found("Technician not found")
    return tech


def get_shift_or_404(shift_id):
    shift = db.technician_shifts.get(shift_id)
    if shift is None:
        raise errors.not_found("TechnicianShift not found")
    return shift


def get_plan_or_404(plan_id):
    plan = db.membership_plans.get(plan_id)
    if plan is None:
        raise errors.not_found("MembershipPlan not found")
    return plan


def get_member_or_404(member_id):
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found("Member not found")
    return member


def get_waiver_or_404(waiver_id):
    waiver = db.waivers.get(waiver_id)
    if waiver is None:
        raise errors.not_found("Waiver not found")
    return waiver


def get_subscription_or_404(subscription_id):
    sub = db.subscriptions.get(subscription_id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    return sub


def get_pack_or_404(pack_id):
    pack = db.credit_packs.get(pack_id)
    if pack is None:
        raise errors.not_found("CreditPack not found")
    return pack


def get_booking_or_404(booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise errors.not_found("Booking not found")
    return booking


def get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise errors.not_found("Invoice not found")
    return inv


# --- Body foreign-key resolution (ERR_REFERENCE_NOT_FOUND, 404) -----------

def ref_location_or_404(location_id):
    loc = db.locations.get(location_id)
    if loc is None:
        raise errors.reference_not_found("Referenced location does not exist")
    return loc


def ref_service_type_or_404(service_type_id):
    st = db.service_types.get(service_type_id)
    if st is None:
        raise errors.reference_not_found("Referenced service type does not exist")
    return st


def ref_room_or_404(room_id):
    room = db.rooms.get(room_id)
    if room is None:
        raise errors.reference_not_found("Referenced room does not exist")
    return room


def ref_plan_or_404(plan_id):
    plan = db.membership_plans.get(plan_id)
    if plan is None:
        raise errors.reference_not_found("Referenced plan does not exist")
    return plan


# --- Ownership (PRD §2.1, ERR_FORBIDDEN 403) ------------------------------

def require_member_ownership(member_id):
    """Member acting must own the member resource; LocationManager/PlatformAdmin
    are opaque proxies and bypass the id comparison."""
    if g.user_role == "Member" and g.user_id != member_id:
        raise errors.forbidden("A member may act only on their own resources")
