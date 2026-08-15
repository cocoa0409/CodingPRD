"""Cascading mutations across entities.

Every cascade branch bumps the affected entity's updated_at/version per PRD §2.8.
"""
from db import db
from util import new_id, utcnow_iso
from services.calcs import (
    bump,
    recompute_credit_exposure,
    recompute_program_balance,
    recompute_run_trim,
    recompute_shift_rollup,
)


# =============================================================================
# Auto-create replenishment order (InventoryProgram -> BoxOrder in DRAFT)
# =============================================================================

def create_replenishment_order(program):
    """Auto-create a DRAFT replenishment BoxOrder per state machine side effect."""
    now = utcnow_iso()
    area = None
    # area_sqft_per_box computed from program's blank dims at 4dp
    from services.calcs import compute_area_sqft_per_box
    area = compute_area_sqft_per_box(program["blank_width_in"], program["blank_length_in"])
    oid = new_id()
    order = {
        "id": oid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": program["customer_id"],
        "board_grade_id": program["board_grade_id"],
        "routing_type": program["routing_type"],
        "board_source": "INTERNAL",
        "sheet_supplier_name": None,
        "quantity": program["replenishment_qty"],
        "blank_width_in": program["blank_width_in"],
        "blank_length_in": program["blank_length_in"],
        "min_ect_required": 0,
        "ink_colors": [],
        "color_count": 0,
        "corrugator_run_id": None,
        "area_sqft_per_box": area,
        "committed_value_dollars": 0,
        "produced_qty": None,
        "invoice_billable_msf": None,
        "invoice_merchandise_dollars": None,
        "invoice_discount_dollars": None,
        "invoice_freight_dollars": None,
        "invoice_total_dollars": None,
        "status": "DRAFT",
    }
    from decimal import Decimal
    order["committed_value_dollars"] = Decimal("0.00")
    db.box_orders[oid] = order
    return order


# =============================================================================
# Run cancel cascade: attached SCHEDULED orders revert to ACCEPTED
# =============================================================================

def cancel_run_orders(run):
    """Revert attached SCHEDULED orders on a cancelled run; clear corrugator_run_id."""
    for o in db.box_orders.values():
        if o.get("corrugator_run_id") == run["id"] and o.get("status") == "SCHEDULED":
            o["status"] = "ACCEPTED"
            o["corrugator_run_id"] = None
            bump(o)
            # Recompute customer exposure after status change
            cust = db.customer_accounts.get(o["customer_id"])
            if cust is not None:
                recompute_credit_exposure(cust)
                bump(cust)
    # Clear outs map for this run
    if run["id"] in db.run_outs:
        db.run_outs[run["id"]] = {}


# =============================================================================
# Booking cancel cascade: order reverts from *_QUEUED or CONVERTING -> AWAITING_CONVERTING
# =============================================================================

def revert_order_for_booking_cancel(booking):
    o = db.box_orders.get(booking["box_order_id"])
    if o is None:
        return
    if o.get("status") in ("DIE_CUT_QUEUED", "SLOTTED_QUEUED", "CONVERTING"):
        # Discard unrecorded produced_qty (remains null)
        o["status"] = "AWAITING_CONVERTING"
        o["produced_qty"] = None
        bump(o)
        cust = db.customer_accounts.get(o["customer_id"])
        if cust is not None:
            recompute_credit_exposure(cust)
            bump(cust)


# =============================================================================
# WorkShift cancel cascade
# =============================================================================

def cancel_shift_cascade(shift):
    """Cancel every SCHEDULED run and QUEUED/RUNNING booking on this shift; revert orders."""
    # First cancel runs (SCHEDULED -> CANCELLED) and revert their orders
    for r in list(db.corrugator_runs.values()):
        if r["work_shift_id"] == shift["id"] and r["status"] == "SCHEDULED":
            r["status"] = "CANCELLED"
            cancel_run_orders(r)
            recompute_run_trim(r)
            bump(r)
    # Then cancel bookings (QUEUED or RUNNING -> CANCELLED) and revert their orders
    for b in list(db.converting_bookings.values()):
        if b["work_shift_id"] == shift["id"] and b["status"] in ("QUEUED", "RUNNING"):
            b["status"] = "CANCELLED"
            revert_order_for_booking_cancel(b)
            bump(b)
    # Recompute capacity rollup on this shift
    recompute_shift_rollup(shift)
