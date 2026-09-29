"""Repair-kit reservation shared by the explicit and the selector-driven route."""

from db import db, new_record
from helpers import model_of_selection, selection_of_build, touch
from services import calc


# Kit allocations may only be raised against an order that is neither CLOSED
# nor CASTING_SHORT (PRD section 3.5).
ALLOCATABLE_BUILD_STATES = ("PLANNED", "ASSEMBLED", "TESTED", "REWORK_REQUIRED")


def model_of_build(build_order):
    return model_of_selection(selection_of_build(build_order))


def kit_window_open(kit):
    """Half-open support window: start inclusive, end exclusive."""
    return kit["support_window_start"] <= db.clock < kit["support_window_end"]


def create_allocation(kit, build_order, requested_qty, selected_by):
    """Price the allocation, move the stock and mint the KitAllocation row."""
    model = model_of_build(build_order)
    charge = calc.allocation_charge(kit, model, requested_qty)
    record = new_record(
        "KitAllocation",
        repair_kit_id=kit["id"],
        build_order_id=build_order["id"],
        requested_qty=requested_qty,
        selected_by=selected_by,
        substitution_penalty_applied_pct=charge["substitution_penalty_applied_pct"],
        parts_extended=charge["parts_extended"],
        handling_rate=charge["handling_rate"],
        handling_fee=charge["handling_fee"],
        total_charge=charge["total_charge"],
        status="RESERVED",
    )
    db.kit_allocations[record["id"]] = record
    kit["qty_on_hand"] -= requested_qty
    kit["qty_reserved"] += requested_qty
    touch(kit)
    return record
