"""Auth: X-User-Role / X-User-ID extraction, role gating, ownership helpers."""

from flask import request

import db
from errors import fail

ROLES = {
    "EventOrganizer",
    "AuthenticityOfficer",
    "SafetyOfficer",
    "UnitCommander",
    "Participant",
    "Vendor",
    "Spectator",
}


def authenticate(allowed_roles, creation=False):
    """Validate auth headers and endpoint role membership.

    Returns (user_id, role). X-User-ID is mandatory on non-creation calls.
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-Role") and request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or unknown X-User-Role")
    if not creation and not uid:
        fail("ERR_UNAUTHENTICATED", "missing X-User-ID")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN", f"role {role} is not permitted on this endpoint")
    return uid, role


# --- entity-backed ownership checks (ERR_FORBIDDEN) -------------------------

def own_unit_scope(uid, unit_id):
    """UnitCommander may act only on its own unit / that unit's members."""
    if unit_id != uid:
        fail("ERR_FORBIDDEN", "unit commander may act only on its own unit")


def own_participant_scope(uid, participant):
    if participant["id"] != uid:
        fail("ERR_FORBIDDEN", "participant may act only on itself")


def own_vendor_scope(uid, vendor):
    if vendor["owner_user_id"] != uid:
        fail("ERR_FORBIDDEN", "vendor may act only on its own record")


def own_order_scope(uid, order):
    if order["buyer_user_id"] != uid:
        fail("ERR_FORBIDDEN", "spectator may act only on its own orders")


# --- referential existence helpers ------------------------------------------

def get_event(event_id):
    ev = db.events.get(event_id)
    if ev is None:
        fail("ERR_EVENT_NOT_FOUND", f"event {event_id} not found")
    return ev


def get_unit(unit_id):
    u = db.units.get(unit_id)
    if u is None:
        fail("ERR_UNIT_NOT_FOUND", f"unit {unit_id} not found")
    return u


def get_participant(pid):
    p = db.participants.get(pid)
    if p is None:
        fail("ERR_PARTICIPANT_NOT_FOUND", f"participant {pid} not found")
    return p


def get_equipment(item_id):
    it = db.equipment.get(item_id)
    if it is None:
        fail("ERR_EQUIPMENT_NOT_FOUND", f"equipment item {item_id} not found")
    return it


def get_inspection(insp_id):
    i = db.inspections.get(insp_id)
    if i is None:
        fail("ERR_INSPECTION_NOT_FOUND", f"inspection {insp_id} not found")
    return i


def get_area(area_id):
    a = db.areas.get(area_id)
    if a is None:
        fail("ERR_AREA_NOT_FOUND", f"site area {area_id} not found")
    return a


def get_slot(slot_id):
    s = db.slots.get(slot_id)
    if s is None:
        fail("ERR_SLOT_NOT_FOUND", f"program slot {slot_id} not found")
    return s


def get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        fail("ERR_ORDER_NOT_FOUND", f"ticket order {order_id} not found")
    return o


def get_pass(pass_id):
    p = db.passes.get(pass_id)
    if p is None:
        fail("ERR_PASS_NOT_FOUND", f"parking pass {pass_id} not found")
    return p


def get_vendor(vendor_id):
    v = db.vendors.get(vendor_id)
    if v is None:
        fail("ERR_VENDOR_NOT_FOUND", f"vendor {vendor_id} not found")
    return v


def get_agreement(agreement_id):
    a = db.agreements.get(agreement_id)
    if a is None:
        fail("ERR_AGREEMENT_NOT_FOUND", f"agreement {agreement_id} not found")
    return a


def get_alert(alert_id):
    a = db.alerts.get(alert_id)
    if a is None:
        fail("ERR_ALERT_NOT_FOUND", f"contingency alert {alert_id} not found")
    return a


def get_allocation(allocation_id):
    a = db.allocations.get(allocation_id)
    if a is None:
        fail("ERR_ALLOCATION_NOT_FOUND", f"allocation {allocation_id} not found")
    return a
