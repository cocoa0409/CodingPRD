"""Domain services: recompute helpers, cascades, and shared state-transition logic.

These functions are used by the route handlers in app.py. They mutate the
in-memory store and bump version/updated_at on every affected versioned record.
"""
from db import db, touch, clock_iso
from common import parse_datetime
from clock import clock
import calculations as calc


# ---------------------------------------------------------------------------
# Member derived fields
# ---------------------------------------------------------------------------
def recompute_member_deposit_hold(member):
    """Member.deposit_hold_cents = sum of deposit holds across HELD reservations."""
    total = 0
    for r in db.reservations.values():
        if r["member_id"] == member["id"] and r["settlement_status"] == "HELD":
            total += r["deposit_hold_cents"]
    if member["deposit_hold_cents"] != total:
        member["deposit_hold_cents"] = total
        touch(member)


# ---------------------------------------------------------------------------
# Inventory release helpers
# ---------------------------------------------------------------------------
def release_unit(reservation, target_status):
    unit = db.units.get(reservation["unit_id"])
    if unit and unit["status"] in ("RESERVED", "OUT"):
        unit["status"] = target_status
        touch(unit)


def release_reservation_gear(reservation, target_status, source_statuses=("ASSIGNED", "OUT")):
    for slot in ("helmet_gear_id", "suit_gear_id"):
        gid = reservation.get(slot)
        if gid:
            gear = db.gear_items.get(gid)
            if gear and gear["status"] in source_statuses:
                gear["status"] = target_status
                touch(gear)


# ---------------------------------------------------------------------------
# Reservation cancellation (used directly and by cascades)
# ---------------------------------------------------------------------------
def cancel_reservation_internal(reservation):
    """Cancel a PENDING or CONFIRMED reservation, releasing holds.

    Releases unit (RESERVED->AVAILABLE) and gear (ASSIGNED->AVAILABLE); for a
    CONFIRMED reservation decrements its departure's rider_count and refunds the
    HELD deposit (HELD->REFUNDED). PENDING reservations hold no inventory.
    """
    was_confirmed = reservation["reservation_status"] == "CONFIRMED"
    # Release unit if held.
    unit = db.units.get(reservation["unit_id"])
    if unit and unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        touch(unit)
    # Release gear if assigned.
    for slot in ("helmet_gear_id", "suit_gear_id"):
        gid = reservation.get(slot)
        if gid:
            gear = db.gear_items.get(gid)
            if gear and gear["status"] == "ASSIGNED":
                gear["status"] = "AVAILABLE"
                touch(gear)

    reservation["reservation_status"] = "CANCELLED"

    if was_confirmed:
        dep = db.tour_departures.get(reservation["tour_departure_id"])
        if dep is not None:
            dep["rider_count"] = max(0, dep["rider_count"] - 1)
            touch(dep)

    # Refund any HELD deposit.
    if reservation["settlement_status"] == "HELD":
        reservation["settlement_status"] = "REFUNDED"

    touch(reservation)

    member = db.members.get(reservation["member_id"])
    if member is not None:
        recompute_member_deposit_hold(member)


# ---------------------------------------------------------------------------
# Guide release helpers
# ---------------------------------------------------------------------------
def deactivate_departure_guides(departure):
    """Deactivate all active GuideAssignments on a departure; release guides."""
    for a in db.guide_assignments.values():
        if a["tour_departure_id"] == departure["id"] and a["active"]:
            a["active"] = False
            guide = db.guides.get(a["guide_id"])
            if guide is not None:
                _maybe_return_guide_available(guide)
    departure["guide_count"] = 0


def _maybe_return_guide_available(guide):
    """Return a guide to AVAILABLE if they hold no other active assignment."""
    has_other_active = any(
        a["guide_id"] == guide["id"] and a["active"]
        for a in db.guide_assignments.values()
    )
    if not has_other_active and guide["status"] == "OFF_DUTY":
        guide["status"] = "AVAILABLE"
        touch(guide)


# ---------------------------------------------------------------------------
# Departure cancellation cascade (PRD §3.6) — used by cancel + closure cascade
# ---------------------------------------------------------------------------
def cancel_departure_internal(departure):
    """Cancel a SCHEDULED/LOCKED departure; cascade reservation cancellation."""
    for r in db.reservations.values():
        if r["tour_departure_id"] != departure["id"]:
            continue
        if r["reservation_status"] in ("PENDING", "CONFIRMED"):
            cancel_reservation_internal(r)
    deactivate_departure_guides(departure)
    departure["status"] = "CANCELLED"
    touch(departure)


# ---------------------------------------------------------------------------
# Trail closure cascade (PRD §3.7)
# ---------------------------------------------------------------------------
def close_trail_cascade(trail):
    """Cancel each SCHEDULED/LOCKED departure on this trail. Returns count cancelled."""
    count = 0
    for dep in db.tour_departures.values():
        if dep["trail_id"] != trail["id"]:
            continue
        if dep["status"] in ("SCHEDULED", "LOCKED"):
            cancel_departure_internal(dep)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Waiver expiry re-evaluation (PRD §3.1)
# ---------------------------------------------------------------------------
def reevaluate_member_waiver(member):
    """Move a stale SIGNED waiver to EXPIRED (clearing the stamp). No-op otherwise."""
    if member["waiver_status"] != "SIGNED":
        return False
    signed_at = member.get("waiver_signed_at")
    if not signed_at:
        return False
    signed_dt = parse_datetime(signed_at)
    expiry_dt = signed_dt + _waiver_validity_delta()
    if clock.now() > expiry_dt:
        member["waiver_status"] = "EXPIRED"
        member["waiver_signed_at"] = None
        touch(member)
        return True
    return False


def reevaluate_all_waivers():
    for member in db.members.values():
        reevaluate_member_waiver(member)


def _waiver_validity_delta():
    from datetime import timedelta
    return timedelta(days=calc.WAIVER_VALIDITY_DAYS)
