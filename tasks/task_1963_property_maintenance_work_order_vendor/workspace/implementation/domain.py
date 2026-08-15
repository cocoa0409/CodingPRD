"""Shared domain services: stock ledger (PRD 2.8), SLA dues, schedule
conflict rules, cascades (PRD 2.9), and resident balance reconciliation."""

from datetime import timedelta

from db import store, touch

PRIORITY_PREFIX = {"EMERGENCY": "emergency", "URGENT": "urgent", "ROUTINE": "routine"}


# --- Stock ledger (PRD 2.8) ---------------------------------------------------

def recompute_restock(part):
    part["restock_status"] = (
        "LOW_STOCK" if part["quantity_on_hand"] <= part["reorder_level"] else "IN_STOCK"
    )


def stock_reserve(part, qty):
    part["quantity_on_hand"] -= qty
    part["reserved_quantity"] += qty
    recompute_restock(part)
    touch(part)


def stock_release(part, qty):
    part["quantity_on_hand"] += qty
    part["reserved_quantity"] -= qty
    recompute_restock(part)
    touch(part)


def stock_consume(part, qty):
    # Consumption writes earmarked stock off: reserved falls, on_hand unchanged.
    part["reserved_quantity"] -= qty
    recompute_restock(part)
    touch(part)


def stock_receive(part, qty):
    part["quantity_on_hand"] += qty
    recompute_restock(part)
    touch(part)


def release_reserved_lines(wo):
    """RESERVED -> RELEASED for every open line of the work order, restoring stock."""
    for line in store.work_order_parts.values():
        if line["work_order_id"] == wo["id"] and line["status"] == "RESERVED":
            line["status"] = "RELEASED"
            touch(line)
            part = store.parts.get(line["part_id"])
            if part is not None:
                stock_release(part, line["quantity"])


# --- Resident chargeback balance (PRD 3.9) -------------------------------------

def recompute_resident_balance(resident_id):
    resident = store.residents.get(resident_id)
    if resident is None:
        return
    total = sum(
        cb["final_amount_cents"] or 0
        for cb in store.chargebacks.values()
        if cb["resident_id"] == resident_id and cb["status"] in ("BILLED", "DISPUTED")
    )
    if total != resident["chargeback_balance_cents"]:
        resident["chargeback_balance_cents"] = total
        touch(resident)


# --- SLA dues (PRD 3.2) ---------------------------------------------------------

def compute_dues(prop, priority, created_at):
    prefix = PRIORITY_PREFIX[priority]
    response_due = created_at + timedelta(hours=prop[f"{prefix}_response_hours"])
    completion_due = created_at + timedelta(hours=prop[f"{prefix}_completion_hours"])
    return response_due, completion_due


# --- Schedule conflicts (PRD 3.3) ------------------------------------------------

def technician_conflict(technician_id, new_start, new_end):
    """Half-open overlap: existing.start < new.end AND new.start < existing.end."""
    for other in store.work_orders.values():
        if (
            other["assigned_technician_id"] == technician_id
            and other["status"] in ("ASSIGNED", "IN_PROGRESS")
            and other["scheduled_start_at"] is not None
            and other["scheduled_start_at"] < new_end
            and new_start < other["scheduled_end_at"]
        ):
            return True
    return False


def vendor_schedule_conflict(vendor_id, new_start, new_end, buffer_minutes):
    """Travel-buffer rule: a gap exactly equal to the buffer is allowed."""
    buf = timedelta(minutes=buffer_minutes)
    for other in store.work_orders.values():
        if (
            other["assigned_vendor_id"] == vendor_id
            and other["status"] in ("ASSIGNED", "IN_PROGRESS")
            and other["scheduled_start_at"] is not None
        ):
            if not (
                new_start >= other["scheduled_end_at"] + buf
                or new_end + buf <= other["scheduled_start_at"]
            ):
                return True
    return False


# --- Assignment field cascade helper (PRD 3.5 / 3.8) ------------------------------

def clear_assignment(wo):
    wo["assignment_type"] = None
    wo["assigned_technician_id"] = None
    wo["assigned_vendor_id"] = None
    wo["scheduled_start_at"] = None
    wo["scheduled_end_at"] = None
    wo["entry_authorization"] = None
    wo["notice_posted_at"] = None
