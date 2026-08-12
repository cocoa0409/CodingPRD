"""State-transition cascades per scaffold §1.2 and PRD §2.10/§3.9."""

import db
from services.common import touch
from services.pricing import refund_amounts


def withdraw_equipment_with_inspections(participant):
    """Depth-2 cascade shared by participant withdraw and unit suspension:
    equipment DECLARED/INSPECTION_DUE/FAILED -> WITHDRAWN, then each such
    item's SCHEDULED inspections -> CANCELLED. Each record versioned."""
    for it in db.equipment.values():
        if it["participant_id"] != participant["id"]:
            continue
        if it["status"] in ("DECLARED", "INSPECTION_DUE", "FAILED"):
            it["status"] = "WITHDRAWN"
            touch(it)
            for ins in db.inspections.values():
                if ins["equipment_item_id"] == it["id"] and ins["status"] == "SCHEDULED":
                    ins["status"] = "CANCELLED"
                    touch(ins)


def withdraw_participant(p):
    """Participant -> WITHDRAWN. From CHECKED_IN there is no equipment cascade."""
    was_checked_in = p["status"] == "CHECKED_IN"
    p["status"] = "WITHDRAWN"
    touch(p)
    if not was_checked_in:
        withdraw_equipment_with_inspections(p)


def suspend_unit(unit):
    """Unit APPROVED -> SUSPENDED with the depth-3 cascade."""
    unit["status"] = "SUSPENDED"
    touch(unit)
    for p in list(db.participants.values()):
        if p["unit_id"] == unit["id"] and p["status"] in (
            "SUBMITTED",
            "CHANGES_REQUESTED",
            "VETTED",
        ):
            withdraw_participant(p)


def cancel_open_flame_slots(event):
    """open_flame slots in PROPOSED/CONFIRMED -> CANCELLED ('CONTINGENCY')."""
    for s in db.slots.values():
        if (
            s["event_id"] == event["id"]
            and s["open_flame"]
            and s["status"] in ("PROPOSED", "CONFIRMED")
        ):
            s["status"] = "CANCELLED"
            s["cancel_reason"] = "CONTINGENCY"
            touch(s)


def restrict_event(event):
    """EVENT_OPEN -> RESTRICTED with the open-flame slot cascade."""
    event["event_posture"] = "RESTRICTED"
    touch(event)
    cancel_open_flame_slots(event)


def release_allocation(alloc):
    if alloc["status"] == "ACTIVE":
        alloc["status"] = "RELEASED"
        touch(alloc)


def revoke_vendor(vendor):
    """Vendor -> REVOKED; releases its ACTIVE allocations."""
    for al in db.allocations.values():
        if al["vendor_id"] == vendor["id"] and al["status"] == "ACTIVE":
            release_allocation(al)
    vendor["status"] = "REVOKED"
    touch(vendor)


def void_pass(ps):
    if ps["status"] == "ACTIVE":
        ps["status"] = "VOIDED"
        touch(ps)


def cancel_event(event):
    """Full-site cancellation cascade per state_machines.Event note."""
    now = db.now()
    event["event_posture"] = "CANCELLED"
    event["cancelled_at"] = now
    touch(event)
    # Hop 2: PAID orders refunded (EVENT_CONTINGENCY), RESERVED orders cancelled.
    for o in db.orders.values():
        if o["event_id"] != event["id"]:
            continue
        if o["status"] == "PAID":
            refund, retained = refund_amounts(event, o, "EVENT_CONTINGENCY")
            o["refund_amount_cents"] = refund
            o["retained_fee_cents"] = retained
            o["refund_reason"] = "EVENT_CONTINGENCY"
            o["refunded_at"] = now
            o["status"] = "REFUNDED"
            touch(o)
            # Hop 3: void that order's ACTIVE passes.
            for ps in db.passes.values():
                if ps["ticket_order_id"] == o["id"] and ps["status"] == "ACTIVE":
                    void_pass(ps)
        elif o["status"] == "RESERVED":
            o["status"] = "CANCELLED"
            touch(o)
    # Slots PROPOSED/CONFIRMED -> CANCELLED ('EVENT_CANCELLED').
    for s in db.slots.values():
        if s["event_id"] == event["id"] and s["status"] in ("PROPOSED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            s["cancel_reason"] = "EVENT_CANCELLED"
            touch(s)
    # ACTIVE allocations on this event's areas -> RELEASED.
    event_area_ids = {a["id"] for a in db.areas.values() if a["event_id"] == event["id"]}
    for al in db.allocations.values():
        if al["site_area_id"] in event_area_ids and al["status"] == "ACTIVE":
            release_allocation(al)
    # Vendors APPROVED/CONTRACTED -> REVOKED.
    for v in db.vendors.values():
        if v["event_id"] == event["id"] and v["status"] in ("APPROVED", "CONTRACTED"):
            revoke_vendor(v)
    # OPEN alerts -> RESOLVED (resolved_at = cancelled_at).
    for a in db.alerts.values():
        if a["event_id"] == event["id"] and a["status"] == "OPEN":
            a["status"] = "RESOLVED"
            a["resolved_at"] = now
            touch(a)
