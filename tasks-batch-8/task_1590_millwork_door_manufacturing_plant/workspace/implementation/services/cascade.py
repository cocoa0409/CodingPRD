"""Shared cascade side effects (PRD §2.10, scaffold state-machine side_effects).

Every cascade mutates its targets as real writes under §2.4: each target gets
its own updated_at refresh and version increment.
"""

import db
from services import pricing


def refresh_roll_counters(roll, bump=True):
    """Recompute serials_available and auto-DEPLETE when the roll is drained.

    Invariant: issued + applied + spoiled + available == serial_capacity.
    ACTIVE -> DEPLETED when available == 0 and issued == 0.
    """
    roll["serials_available"] = (roll["serial_capacity"] - roll["serials_issued"]
                                 - roll["serials_applied"] - roll["serials_spoiled"])
    if roll["status"] == "ACTIVE" and roll["serials_available"] == 0 and roll["serials_issued"] == 0:
        roll["status"] = "DEPLETED"
    db.touch(roll) if bump else None


def void_allocation(allocation, bump_roll=True):
    """Void an ISSUED / APPLIED / VERIFIED allocation and move its serials to spoiled."""
    roll = db.fire_label_rolls.get(allocation["roll_id"])
    if allocation["status"] == "ISSUED":
        if roll is not None:
            roll["serials_issued"] -= allocation["serial_count"]
            roll["serials_spoiled"] += allocation["serial_count"]
    elif allocation["status"] in ("APPLIED", "VERIFIED"):
        if roll is not None:
            roll["serials_applied"] -= allocation["serial_count"]
            roll["serials_spoiled"] += allocation["serial_count"]
    allocation["status"] = "VOIDED"
    db.touch(allocation)
    if roll is not None and bump_roll:
        refresh_roll_counters(roll, bump=True)


def cancel_program_slots(program):
    """BOOKED slots of this program -> CANCELLED."""
    for slot in db.moulder_setup_slots.values():
        if slot["program_id"] == program["id"] and slot["status"] == "BOOKED":
            slot["status"] = "CANCELLED"
            db.touch(slot)


def supersede_drawing(drawing):
    """APPROVED drawing -> SUPERSEDED; its programs CREATED/SETUP_BOOKED/PROVEN -> VOIDED;
    those programs' BOOKED slots -> CANCELLED."""
    if drawing["status"] == "APPROVED":
        drawing["status"] = "SUPERSEDED"
        db.touch(drawing)
        for program in db.machining_programs.values():
            if program["drawing_id"] == drawing["id"] and program["status"] in ("CREATED", "SETUP_BOOKED", "PROVEN"):
                cancel_program_slots(program)
                program["status"] = "VOIDED"
                db.touch(program)


def cancel_order_cascade(order):
    """Deep order-cancellation cascade (PRD §3.2)."""
    # Openings in non-terminal states -> CANCELLED on both axes; detach from trips.
    for opening in db.openings.values():
        if opening["order_id"] != order["id"]:
            continue
        fab_terminal = opening["fab_status"] == "CANCELLED"
        ship_terminal = opening["ship_status"] in ("ACCEPTED", "CANCELLED")
        if fab_terminal and ship_terminal:
            continue
        trip_id = opening.get("assigned_trip_id")
        if not fab_terminal:
            opening["fab_status"] = "CANCELLED"
        opening["ship_status"] = "CANCELLED"
        opening["assigned_trip_id"] = None
        db.touch(opening)
        if trip_id:
            trip = db.delivery_trips.get(trip_id)
            if trip is not None:
                trip["leaves_committed"] = sum(
                    o["leaf_count"] for o in db.openings.values()
                    if o.get("assigned_trip_id") == trip["id"] and o["ship_status"] == "SCHEDULED"
                )
                db.touch(trip)
    # Shop drawings: DRAFT/SUBMITTED -> VOID; APPROVED -> SUPERSEDED.
    for drawing in db.shop_drawings.values():
        if drawing["order_id"] != order["id"]:
            continue
        if drawing["status"] in ("DRAFT", "SUBMITTED"):
            drawing["status"] = "VOID"
            db.touch(drawing)
        elif drawing["status"] == "APPROVED":
            supersede_drawing(drawing)
    # Machining programs of the order -> VOIDED; their BOOKED slots -> CANCELLED.
    for program in db.machining_programs.values():
        if program["order_id"] == order["id"] and program["status"] in ("CREATED", "SETUP_BOOKED", "PROVEN", "RELEASED"):
            cancel_program_slots(program)
            program["status"] = "VOIDED"
            db.touch(program)
    # Label allocations of the order's openings in ISSUED/APPLIED -> VOIDED (serials spoiled).
    for allocation in db.label_allocations.values():
        opening = db.openings.get(allocation["opening_id"])
        if opening is None or opening["order_id"] != order["id"]:
            continue
        if allocation["status"] in ("ISSUED", "APPLIED"):
            void_allocation(allocation)


def compute_contract_into_order(order):
    """APPROVED-cascade side effect: strike the contract price onto the order."""
    merch, freight, contract = pricing.compute_contract_pricing(order)
    order["merchandise_total_cents"] = merch
    order["freight_fee_cents"] = freight
    order["contract_price_cents"] = contract
