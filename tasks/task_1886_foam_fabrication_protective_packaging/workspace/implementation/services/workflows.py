"""Cross-entity cascades and compensating actions (PRD §2.9, §3.2, §3.3, §3.6).

Every resource touched by a cascade is mutated individually: its updated_at
refreshes and its version increments.
"""
import db
from services.common import touch


def cancel_production_order(order):
    """Cancel a QUOTED or CONFIRMED production order with compensation (§2.9):
    confirmed die-cut orders return their amortization charge to the tooling
    and free the machine window (CANCELLED windows no longer block bookings).
    """
    was_confirmed = order["fab_status"] == "CONFIRMED"
    order["fab_status"] = "CANCELLED"
    if was_confirmed and order.get("tooling_amort_cents"):
        tooling_id = order.get("_tooling_id")
        tooling = db.toolings.get(tooling_id) if tooling_id else None
        if tooling is None:
            # Fall back to any tooling of the linked program (defensive).
            from services.calculations import toolings_for_program
            cands = toolings_for_program(order["cut_program_id"])
            tooling = cands[0] if cands else None
        if tooling is not None:
            tooling["amortized_cents"] -= order["tooling_amort_cents"]
            touch(tooling)
    touch(order)


def obsolete_cut_program(program):
    """Transition a DRAFT/NESTED/LOCKED cut program to OBSOLETE and cancel the
    open production orders built on it (PRD §3.2 full revision cascade; §3.3
    supersede cascade)."""
    if program["status"] not in ("DRAFT", "NESTED", "LOCKED"):
        return
    program["status"] = "OBSOLETE"
    touch(program)
    for order in db.production_orders.values():
        if order["cut_program_id"] == program["id"] and order["fab_status"] in ("QUOTED", "CONFIRMED"):
            cancel_production_order(order)


def return_spec_for_revision(spec):
    """IN_VALIDATION/VALIDATED -> DRAFT with revision increment and full cascade."""
    spec["revision_no"] += 1
    spec["status"] = "DRAFT"
    for program in db.cut_programs.values():
        if program["package_spec_id"] == spec["id"] and program["status"] in ("DRAFT", "NESTED", "LOCKED"):
            obsolete_cut_program(program)
    touch(spec)


def cancel_release_order(release):
    """PENDING/ALLOCATED -> CANCELLED; an allocated cancellation returns its
    reservation to the program's unreserved stock."""
    program = db.inventory_programs.get(release["inventory_program_id"])
    if release["status"] == "ALLOCATED" and program is not None:
        program["reserved_qty"] -= release["qty"]
        touch(program)
    release["status"] = "CANCELLED"
    touch(release)


def suspend_inventory_program(program):
    """ACTIVE -> SUSPENDED; cancels every PENDING/ALLOCATED release order with
    reserved-stock compensation."""
    program["status"] = "SUSPENDED"
    for release in db.release_orders.values():
        if release["inventory_program_id"] == program["id"] and release["status"] in ("PENDING", "ALLOCATED"):
            cancel_release_order(release)
    touch(program)
