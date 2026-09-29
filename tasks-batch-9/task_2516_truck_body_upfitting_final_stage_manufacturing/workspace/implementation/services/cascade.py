"""Cascading side effects and the shared state-machine helpers.

Every row a cascade touches gets its own version increment and updated_at
refresh; a row visited by more than one hop of the same request is still bumped
exactly once (PRD sections 2.10 / 3.3 / 3.6).
"""

import db
from services import calc, lookup
from validation import as_date

LIVE_SLOT_STATUSES = ("QUEUED", "SCHEDULED", "IN_BUILD")
BOOKED_SLOT_STATUSES = ("SCHEDULED", "IN_BUILD")


# --------------------------------------------------------------------------
# Bay and chassis occupancy
# --------------------------------------------------------------------------
def bay_overlap_count(bay_id, start_date, end_date, exclude_slot_id=None):
    """Bay contention is an aggregate, half-open comparison: two slots collide
    when existing.start_date < new.end_date and new.start_date < existing.end_date,
    so a slot ending the very day another begins does not collide."""
    start = as_date(start_date)
    end = as_date(end_date)
    count = 0
    for other in lookup.slots_in_bay(bay_id):
        if exclude_slot_id is not None and other["id"] == exclude_slot_id:
            continue
        if other["status"] not in BOOKED_SLOT_STATUSES:
            continue
        if as_date(other["start_date"]) < end and start < as_date(other["end_date"]):
            count += 1
    return count


def chassis_occupancy_conflict(chassis_id, start_date, end_date, exclude_slot_id=None):
    """A physical truck is exclusive over a closed interval: existing.start_date
    <= new.end_date and new.start_date <= existing.end_date, so even touching
    endpoints collide."""
    if not chassis_id:
        return None
    start = as_date(start_date)
    end = as_date(end_date)
    for other in db.all_rows(db.build_slots):
        if exclude_slot_id is not None and other["id"] == exclude_slot_id:
            continue
        if other.get("chassis_id") != chassis_id:
            continue
        if other["status"] not in LIVE_SLOT_STATUSES:
            continue
        if as_date(other["start_date"]) <= end and start <= as_date(other["end_date"]):
            return other
    return None


# --------------------------------------------------------------------------
# queue_promotion_selector (PRD section 3.7)
# --------------------------------------------------------------------------
def promote_from_queue(bay_id):
    """Runs whenever a bay window is freed.  Candidates are the bay's QUEUED
    slots whose order is at RELEASED, ordered by start_date then created_at —
    the row id never breaks the tie.  The first candidate that still fits both
    the bay ceiling and its truck's exclusivity is promoted, and the walk stops
    there: at most one promotion per freed window.  An empty pool is a normal
    no-op."""
    bay = db.work_bays.get(bay_id)
    if bay is None or bay.get("status") != "ACTIVE":
        return None

    candidates = []
    for slot in lookup.slots_in_bay(bay_id):
        if slot["status"] != "QUEUED":
            continue
        order = db.upfit_orders.get(slot["upfit_order_id"])
        if order is None or order.get("build_status") != "RELEASED":
            continue
        candidates.append(slot)
    candidates.sort(key=lambda s: (as_date(s["start_date"]), s.get("_seq") or 0))

    for slot in candidates:
        booked = bay_overlap_count(
            bay_id, slot["start_date"], slot["end_date"], exclude_slot_id=slot["id"]
        )
        if booked >= int(bay["concurrent_capacity"]):
            continue
        if chassis_occupancy_conflict(
            slot.get("chassis_id"), slot["start_date"], slot["end_date"], exclude_slot_id=slot["id"]
        ):
            continue
        slot["status"] = "SCHEDULED"
        slot["promoted_from_queue_at"] = db.clock_now_iso()
        db.touch(slot)
        order = db.upfit_orders.get(slot["upfit_order_id"])
        if order is not None and order.get("build_status") == "RELEASED":
            order["build_status"] = "SCHEDULED"
            db.touch(order)
        return slot
    return None


# --------------------------------------------------------------------------
# Compliance dimension step-backs (PRD section 3.8)
# --------------------------------------------------------------------------
def void_labels(order):
    """Stamp voided_at, from the logical clock, on every label of the order that
    is still standing.  A label is never mutated otherwise."""
    stamped = []
    for label in lookup.labels_of(order["id"]):
        if label.get("voided_at") is None:
            label["voided_at"] = db.clock_now_iso()
            stamped.append(label)
    return stamped


def compliance_step_back(order, basis):
    """Voiding an approved certification walks the compliance dimension back one
    rung.  Returns True when the order left LABELED."""
    left_labeled = False
    if basis == "AS_DESIGNED":
        if order.get("compliance_status") == "DESIGN_CERTIFIED":
            order["compliance_status"] = "NOT_STARTED"
            db.touch(order)
    else:
        if order.get("compliance_status") == "LABELED":
            void_labels(order)
            order["compliance_status"] = "DESIGN_CERTIFIED"
            db.touch(order)
            left_labeled = True
        elif order.get("compliance_status") == "MEASURED_CERTIFIED":
            order["compliance_status"] = "DESIGN_CERTIFIED"
            db.touch(order)
    return left_labeled


def void_certifications(order, reason, basis=None, include_drafts=False, exclude_id=None):
    """Void the order's certifications matching `basis`.  Any approved row that
    is voided drags the compliance dimension back with it."""
    left_labeled = False
    for cert in lookup.certifications_of(order["id"]):
        if exclude_id is not None and cert["id"] == exclude_id:
            continue
        if basis is not None and cert["basis"] != basis:
            continue
        if cert["status"] == "APPROVED":
            was_approved = True
        elif cert["status"] == "DRAFT" and include_drafts:
            was_approved = False
        else:
            continue
        cert["status"] = "VOIDED"
        cert["voided_reason"] = reason
        db.touch(cert)
        if was_approved:
            if compliance_step_back(order, cert["basis"]):
                left_labeled = True
    return left_labeled


def component_set_changed(order):
    """Hops two through four of the equipment install / removal cascade."""
    left_labeled = void_certifications(order, "COMPONENT_SET_CHANGED", basis="AS_MEASURED")
    if left_labeled and order.get("build_status") == "BUILD_COMPLETE":
        order["build_status"] = "IN_BUILD"
        db.touch(order)
        closed = [s for s in lookup.slots_of(order["id"]) if s["status"] == "CLOSED"]
        if closed:
            closed.sort(key=db.sort_key)
            newest = closed[-1]
            newest["status"] = "IN_BUILD"
            db.touch(newest)
    return left_labeled


# --------------------------------------------------------------------------
# Chassis return cascade (PRD section 3.3)
# --------------------------------------------------------------------------
def chassis_return_cascade(unit):
    """Four hops, identical on the ALLOCATED -> RETURNED and IN_UPFIT ->
    RETURNED edges.  An unallocated unit's return is a single-row change."""
    order_id = unit.get("allocated_upfit_order_id")
    unit["allocated_upfit_order_id"] = None
    if not order_id:
        return
    order = db.upfit_orders.get(order_id)
    if order is None:
        return
    # hop one
    order["chassis_id"] = None
    order["build_status"] = "CHASSIS_HOLD"
    db.touch(order)
    # hop two
    freed_bays = []
    for slot in lookup.slots_of(order["id"]):
        if slot["status"] not in LIVE_SLOT_STATUSES:
            continue
        was = slot["status"]
        slot["status"] = "CANCELLED"
        db.touch(slot)
        if was in BOOKED_SLOT_STATUSES:
            freed_bays.append(slot["work_bay_id"])
    # hops three and four
    for bay_id in freed_bays:
        promote_from_queue(bay_id)


# --------------------------------------------------------------------------
# Order cancellation cascade (PRD section 3.4)
# --------------------------------------------------------------------------
def order_cancel_cascade(order):
    """Three conditional parts, identical on every accepted from-state."""
    freed_bays = []
    for slot in lookup.slots_of(order["id"]):
        if slot["status"] not in ("QUEUED", "SCHEDULED"):
            continue
        was = slot["status"]
        slot["status"] = "CANCELLED"
        db.touch(slot)
        if was == "SCHEDULED":
            freed_bays.append(slot["work_bay_id"])
    for bay_id in freed_bays:
        promote_from_queue(bay_id)

    for inst in lookup.installations_of(order["id"]):
        if inst["status"] != "PLANNED":
            continue
        inst["status"] = "REMOVED"
        inst["allocated_flow_gpm"] = 0
        inst["hydraulic_status"] = "NOT_APPLICABLE"
        db.touch(inst)
    calc.run_pto_waterfall(order)

    if order.get("chassis_id"):
        unit = db.chassis_units.get(order["chassis_id"])
        if unit is not None:
            unit["status"] = "INSPECTED"
            unit["allocated_upfit_order_id"] = None
            db.touch(unit)


# --------------------------------------------------------------------------
# Slot bubble-ups (PRD section 3.7)
# --------------------------------------------------------------------------
def close_slot_bubble_up(order):
    """After a closure, an order with no live slots and a mounted body completes."""
    live = [s for s in lookup.slots_of(order["id"]) if s["status"] in LIVE_SLOT_STATUSES]
    if live:
        return False
    if order.get("body_install_status") != "INSTALLED":
        return False
    if order.get("build_status") != "IN_BUILD":
        return False
    order["build_status"] = "BUILD_COMPLETE"
    db.touch(order)
    return True


def cancel_slot_step_back(order):
    """After cancelling a booked window, an order left with nothing booked steps
    back SCHEDULED -> RELEASED."""
    booked = [s for s in lookup.slots_of(order["id"]) if s["status"] in BOOKED_SLOT_STATUSES]
    if booked:
        return False
    if order.get("build_status") != "SCHEDULED":
        return False
    order["build_status"] = "RELEASED"
    db.touch(order)
    return True
