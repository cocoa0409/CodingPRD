"""Shared domain helpers: lookups, scoped existence checks, derived-field
recomputation, and parent state bubble-up.

Every recomputation that changes a resource is a genuine mutation: it refreshes
updated_at and bumps version (PRD §2.5).
"""

import errors
from db import DB, stamp_create, touch
from services import calc


# --------------------------------------------------------------------------- #
# Lookups (bureau-scoped)
# --------------------------------------------------------------------------- #
def get_or_404(collection, entity_id, bureau_id=None):
    ent = collection.get(entity_id)
    if ent is None:
        raise errors.not_found()
    if bureau_id is not None and ent.get("bureau_id") != bureau_id:
        raise errors.not_found()
    return ent


def ref_or_404(collection, entity_id, bureau_id):
    """Body-FK resolution within the same bureau -> ERR_REFERENCE_NOT_FOUND."""
    ent = collection.get(entity_id)
    if ent is None or ent.get("bureau_id") != bureau_id:
        raise errors.reference_not_found()
    return ent


# --------------------------------------------------------------------------- #
# Order line / order helpers
# --------------------------------------------------------------------------- #
def active_lines_of_order(order_id):
    return [
        l for l in DB.order_lines.values()
        if l["order_id"] == order_id and l["status"] == "ACTIVE"
    ]


def lines_of_order(order_id):
    return [l for l in DB.order_lines.values() if l["order_id"] == order_id]


def recompute_order_totals(order):
    active = active_lines_of_order(order["id"])
    parts, finishing, rush, grand = calc.order_totals(active, order["lead_tier"])
    changed = (
        order["parts_subtotal_cents"] != parts
        or order["finishing_subtotal_cents"] != finishing
        or order["rush_surcharge_cents"] != rush
        or order["grand_total_cents"] != grand
    )
    order["parts_subtotal_cents"] = parts
    order["finishing_subtotal_cents"] = finishing
    order["rush_surcharge_cents"] = rush
    order["grand_total_cents"] = grand
    if changed:
        touch(order)
    return order


def recompute_line_finishing_total(line):
    """finishing_total_cents = sum(addon_cents for that line's tasks) * quantity."""
    addon_sum = sum(
        int(t["addon_cents"]) for t in DB.finishing_tasks.values()
        if t["order_line_id"] == line["id"]
    )
    new_total = addon_sum * int(line["quantity"])
    if line.get("finishing_total_cents", 0) != new_total:
        line["finishing_total_cents"] = new_total
        touch(line)
    return line


# --------------------------------------------------------------------------- #
# Machine utilization
# --------------------------------------------------------------------------- #
def recompute_machine_utilization(machine):
    bureau = DB.bureaus[machine["bureau_id"]]
    runs = [r for r in DB.print_runs.values() if r["machine_id"] == machine["id"]]
    scheduled = sum(int(r["duration_min"]) for r in runs if r["status"] in ("QUEUED", "PRINTING"))
    active = sum(int(r["duration_min"]) for r in runs if r["status"] == "PRINTING")
    util, active_util = calc.machine_utilization(scheduled, active, bureau["shift_capacity_minutes"])
    changed = (
        machine["scheduled_minutes"] != scheduled
        or machine["active_minutes"] != active
        or machine["utilization_pct"] != util
        or machine["active_utilization_pct"] != active_util
    )
    machine["scheduled_minutes"] = scheduled
    machine["active_minutes"] = active
    machine["utilization_pct"] = util
    machine["active_utilization_pct"] = active_util
    if changed:
        touch(machine)
    return machine


# --------------------------------------------------------------------------- #
# Spool conservation
# --------------------------------------------------------------------------- #
def recompute_spool(spool):
    runs = [r for r in DB.print_runs.values() if r["spool_id"] == spool["id"]]
    committed = sum(int(r["run_grams"]) for r in runs if r["status"] in ("QUEUED", "PRINTING"))
    consumed = sum(int(r["run_grams"]) for r in runs if r["status"] in ("DONE", "FAILED"))
    remaining = int(spool["grams_total"]) - committed - consumed
    new_status = "DEPLETED" if remaining == 0 else "LOADED"
    changed = (
        spool["grams_committed"] != committed
        or spool["grams_consumed"] != consumed
        or spool["grams_remaining"] != remaining
        or spool["status"] != new_status
    )
    spool["grams_committed"] = committed
    spool["grams_consumed"] = consumed
    spool["grams_remaining"] = remaining
    spool["status"] = new_status
    if changed:
        touch(spool)
    return spool


# --------------------------------------------------------------------------- #
# Customer wallet ledger aggregates
# --------------------------------------------------------------------------- #
def recompute_customer_aggregates(customer):
    """escrow_held / captured_revenue are derived sums over the customer's
    orders by payment_status. wallet_balance and lifetime_deposits are mutated
    directly by the movements; they are not recomputed here.
    """
    orders = [o for o in DB.orders.values() if o["customer_id"] == customer["id"]]
    escrow = sum(int(o["grand_total_cents"]) for o in orders if o["payment_status"] == "ESCROWED")
    captured = sum(int(o["grand_total_cents"]) for o in orders if o["payment_status"] == "CAPTURED")
    changed = (
        customer["escrow_held_cents"] != escrow
        or customer["captured_revenue_cents"] != captured
    )
    customer["escrow_held_cents"] = escrow
    customer["captured_revenue_cents"] = captured
    if changed:
        touch(customer)
    return customer


# --------------------------------------------------------------------------- #
# Order fulfillment bubble-up (PRD §2.5, §3.6, §3.4)
# --------------------------------------------------------------------------- #
def _order_all_active_lines_done(order):
    """Every ACTIVE line of the order has a terminal DONE PrintRun."""
    active = active_lines_of_order(order["id"])
    if not active:
        return False
    for line in active:
        runs = [r for r in DB.print_runs.values() if r["order_line_id"] == line["id"]]
        if not any(r["status"] == "DONE" for r in runs):
            return False
    return True


def order_has_finishing_tasks(order):
    line_ids = {l["id"] for l in lines_of_order(order["id"])}
    return any(t["order_line_id"] in line_ids for t in DB.finishing_tasks.values())


def order_all_finishing_resolved(order):
    line_ids = {l["id"] for l in lines_of_order(order["id"])}
    tasks = [t for t in DB.finishing_tasks.values() if t["order_line_id"] in line_ids]
    if not tasks:
        return True
    return all(t["status"] in ("DONE", "SKIPPED") for t in tasks)


def bubble_on_run_complete(order):
    """When every active line now has a DONE run: IN_PRODUCTION -> POST_PROCESSING
    (if finishing tasks exist) else -> READY."""
    if order["fulfillment_status"] != "IN_PRODUCTION":
        return
    if not _order_all_active_lines_done(order):
        return
    if order_has_finishing_tasks(order):
        order["fulfillment_status"] = "POST_PROCESSING"
    else:
        order["fulfillment_status"] = "READY"
    touch(order)


def bubble_on_finishing_resolved(order):
    """POST_PROCESSING -> READY when every finishing task is DONE/SKIPPED."""
    if order["fulfillment_status"] != "POST_PROCESSING":
        return
    if order_all_finishing_resolved(order):
        order["fulfillment_status"] = "READY"
        touch(order)
