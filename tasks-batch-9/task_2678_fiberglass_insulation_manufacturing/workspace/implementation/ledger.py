"""Derived ledgers (plant cullet, lot coverage, order roll-up, cycle totals)
and every cascade described in PRD 2.7, 3.1, 3.2, 3.6, 3.7, 3.8 and 3.9."""

from decimal import Decimal

import calc
from calc import D0_2, D0_4, q2, q4
from db import ordered, store, touch

LIVE_LOT_STATUSES = ("AVAILABLE", "ALLOCATED")
DEAD_LOT_STATUSES = ("QUARANTINED", "REPACKED", "CONSUMED", "SCRAPPED")
CHARGED_RUN_STATUSES = ("MELTING", "CURING", "PACKAGED", "CLOSED")
OPEN_ORDER_STATUSES = ("SUBMITTED", "PARTIAL", "BACKORDERED")


def set_fields(row, **updates):
    changed = False
    for key, value in updates.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


# ---------------------------------------------------------------------------
# collection scans
# ---------------------------------------------------------------------------

def plant_batches(plant_id):
    return ordered([b for b in store.cullet.values() if b["plant_id"] == plant_id])


def plant_runs(plant_id):
    return ordered([r for r in store.runs.values() if r["plant_id"] == plant_id])


def product_line_runs(product_line_id):
    return ordered([r for r in store.runs.values() if r["product_line_id"] == product_line_id])


def product_line_cycles(product_line_id):
    return ordered([c for c in store.cycles.values() if c["product_line_id"] == product_line_id])


def binder_product_lines(binder_id):
    return ordered([p for p in store.product_lines.values()
                    if p["binder_formulation_id"] == binder_id])


def run_lots(run_id):
    return ordered([l for l in store.lots.values() if l["production_run_id"] == run_id])


def lot_lines(lot_id):
    return ordered([l for l in store.lines.values() if l["inventory_lot_id"] == lot_id])


def order_lines(order_id):
    return ordered([l for l in store.lines.values() if l["channel_order_id"] == order_id])


def cycle_lines(cycle_id):
    return ordered([l for l in store.lines.values() if l["allocation_cycle_id"] == cycle_id])


def product_line_tests(product_line_id):
    return ordered([t for t in store.thermal_tests.values()
                    if t["product_line_id"] == product_line_id])


# ---------------------------------------------------------------------------
# plant cullet ledger (PRD 3.1)
# ---------------------------------------------------------------------------

def recompute_plant_ledger(plant, bump=True):
    received = Decimal(0)
    charged = Decimal(0)
    rejected = Decimal(0)
    for batch in plant_batches(plant["id"]):
        mass = Decimal(batch["mass_kg"])
        received += mass
        if batch["status"] == "CHARGED":
            charged += mass
        elif batch["status"] == "REJECTED":
            rejected += mass
    total_charge = Decimal(0)
    for run in plant_runs(plant["id"]):
        if run["run_status"] in CHARGED_RUN_STATUSES and run.get("total_charge_kg") is not None:
            total_charge += Decimal(run["total_charge_kg"])
    updates = {
        "cullet_received_kg_ytd": q2(received),
        "cullet_charged_kg_ytd": q2(charged),
        "cullet_rejected_kg_ytd": q2(rejected),
        "cullet_on_hand_kg": q2(received - charged - rejected),
        "total_charge_kg_ytd": q2(total_charge),
        "cullet_fraction_ytd": calc.cullet_fraction(q2(charged), q2(total_charge)),
    }
    changed = set_fields(plant, **updates)
    if changed and bump:
        touch(plant)
    return changed


def tighten_posture_if_needed(plant):
    """PRD 3.1: evaluated by the server at the end of a furnace charge."""
    if plant["melt_posture"] == "OPEN" and \
            Decimal(plant["cullet_fraction_ytd"]) >= Decimal(plant["cullet_restrict_fraction"]):
        return set_fields(plant, melt_posture="RESTRICTED",
                          posture_reason="CULLET_FRACTION_AT_RESTRICT_LEVEL")
    return False


# ---------------------------------------------------------------------------
# lot / order / cycle ledgers (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------

def _lot_allocated(lot):
    total = Decimal(0)
    for line in lot_lines(lot["id"]):
        if line["status"] == "ALLOCATED":
            total += Decimal(line["allocated_sqft"])
    return q2(total)


def recompute_lot(lot, bump=True):
    updates = {"allocated_sqft": _lot_allocated(lot)}
    if lot["status"] in DEAD_LOT_STATUSES:
        updates["available_sqft"] = D0_2
    else:
        available = q2(Decimal(lot["produced_sqft"]) - updates["allocated_sqft"])
        updates["available_sqft"] = available
        updates["status"] = "ALLOCATED" if available == 0 else "AVAILABLE"
    changed = set_fields(lot, **updates)
    if changed and bump:
        touch(lot)
    return changed


def recompute_order(order, bump=True, derive_backorder=False):
    if order["status"] in ("CANCELLED", "SHIPPED"):
        return False
    total = Decimal(0)
    for line in order_lines(order["id"]):
        if line["status"] == "ALLOCATED":
            total += Decimal(line["allocated_sqft"])
    allocated = q2(total)
    requested = Decimal(order["requested_sqft"])
    fill = q2(allocated / requested * Decimal(100)) if requested > 0 else D0_2
    status = order["status"]
    if allocated == requested:
        status = "ALLOCATED"
    elif allocated > 0:
        status = "PARTIAL"
    elif derive_backorder or order["status"] in ("ALLOCATED", "PARTIAL", "BACKORDERED"):
        status = "BACKORDERED"
    changed = set_fields(order, allocated_sqft=allocated, fill_rate_pct=fill, status=status)
    if changed and bump:
        touch(order)
    return changed


def recompute_cycle(cycle, bump=True):
    total = Decimal(0)
    for line in cycle_lines(cycle["id"]):
        if line["status"] in ("PROPOSED", "ALLOCATED"):
            total += Decimal(line["allocated_sqft"])
    allocated = q2(total)
    updates = {"allocated_sqft": allocated}
    if cycle.get("allocatable_sqft") is not None:
        updates["unallocated_sqft"] = q2(Decimal(cycle["allocatable_sqft"]) - allocated)
    changed = set_fields(cycle, **updates)
    if changed and bump:
        touch(cycle)
    return changed


# ---------------------------------------------------------------------------
# line revocation fan-out
# ---------------------------------------------------------------------------

def revoke_lines(lines, reason, note=None, skip_lot_ids=(), skip_cycle_ids=()):
    lot_ids = []
    order_ids = []
    cycle_ids = []
    for line in lines:
        set_fields(line, status="REVOKED", revoke_reason=reason)
        if note is not None:
            line["_revoke_note"] = note
        touch(line)
        for bucket, key in ((lot_ids, "inventory_lot_id"),
                            (order_ids, "channel_order_id"),
                            (cycle_ids, "allocation_cycle_id")):
            if line[key] not in bucket:
                bucket.append(line[key])
    for lot_id in lot_ids:
        if lot_id in skip_lot_ids:
            continue
        lot = store.lots.get(lot_id)
        if lot is not None:
            recompute_lot(lot)
    for order_id in order_ids:
        order = store.orders.get(order_id)
        if order is not None:
            recompute_order(order)
    for cycle_id in cycle_ids:
        if cycle_id in skip_cycle_ids:
            continue
        cycle = store.cycles.get(cycle_id)
        if cycle is not None:
            recompute_cycle(cycle)


def live_lines_of_lot(lot):
    return [l for l in lot_lines(lot["id"]) if l["status"] in ("PROPOSED", "ALLOCATED")]


def quarantine_lot(lot, reason, bump=True):
    """PRD 3.7 hold / PRD 3.6 nonconforming cascade hop 2."""
    revoke_lines(live_lines_of_lot(lot), "LOT_QUARANTINED", skip_lot_ids=(lot["id"],))
    set_fields(lot, status="QUARANTINED", quarantine_reason=reason)
    recompute_lot(lot, bump=False)
    if bump:
        touch(lot)


# ---------------------------------------------------------------------------
# run holds, cycle cancellation, SKU and binder suspension cascades
# ---------------------------------------------------------------------------

def hold_run(run, reason):
    if run["run_status"] == "SCHEDULED":
        set_fields(run, run_status="HELD", hold_reason=reason)
        touch(run)


def cancel_cycle(cycle, reason=None, revoke_reason="CYCLE_CANCELLED", bump=True):
    lines = [l for l in cycle_lines(cycle["id"]) if l["status"] in ("PROPOSED", "ALLOCATED")]
    revoke_lines(lines, revoke_reason, skip_cycle_ids=(cycle["id"],))
    set_fields(cycle, status="CANCELLED")
    if reason is not None:
        cycle["_cancel_reason"] = reason
    recompute_cycle(cycle, bump=False)
    if bump:
        touch(cycle)


def suspend_product_line(product_line, cancel_cycles=True):
    set_fields(product_line, certification_status="SUSPENDED")
    touch(product_line)
    for run in product_line_runs(product_line["id"]):
        hold_run(run, "PRODUCT_LINE_SUSPENDED")
    if cancel_cycles:
        for cycle in product_line_cycles(product_line["id"]):
            if cycle["status"] in ("OPEN", "PROPOSED"):
                cancel_cycle(cycle)


def cascade_binder_suspension(binder):
    """PRD 3.2: SKUs on the formulation suspend, then their scheduled runs hold."""
    affected = []
    for product_line in binder_product_lines(binder["id"]):
        if product_line["certification_status"] in ("DRAFT", "PENDING_CERTIFICATION",
                                                    "CERTIFIED", "DERATED"):
            suspend_product_line(product_line, cancel_cycles=False)
            affected.append(product_line)
    return affected


def nonconforming_run_cascade(run):
    """PRD 3.6: quarantine the run's lots and unwind their coverage."""
    for lot in run_lots(run["id"]):
        if lot["status"] in LIVE_LOT_STATUSES:
            quarantine_lot(lot, "RUN_NONCONFORMING")


def freeze_plant_cascade(plant):
    """PRD 3.9: four-hop emissions freeze.  The plant row itself is bumped by
    the caller; every other affected row is bumped here."""
    set_fields(plant, melt_posture="FROZEN", posture_reason="EMISSIONS_EXCEEDANCE")
    # Every SCHEDULED run of the plant goes on hold with PLANT_FROZEN.
    for run in plant_runs(plant["id"]):
        hold_run(run, "PLANT_FROZEN")
    plant_line_ids = set(p["id"] for p in store.product_lines.values()
                         if p["plant_id"] == plant["id"])
    binder_ids = []
    for product_line in store.product_lines.values():
        if product_line["plant_id"] != plant["id"]:
            continue
        if product_line["binder_formulation_id"] not in binder_ids:
            binder_ids.append(product_line["binder_formulation_id"])
    suspended_lines = []
    for binder_id in binder_ids:
        binder = store.binders.get(binder_id)
        if binder is None:
            continue
        if binder["status"] != "CERTIFIED" or binder["formaldehyde_free"] is True:
            continue
        set_fields(binder, status="SUSPENDED")
        touch(binder)
        suspended_lines.extend(cascade_binder_suspension(binder))
    for product_line in suspended_lines:
        for cycle in product_line_cycles(product_line["id"]):
            if cycle["status"] in ("OPEN", "PROPOSED"):
                cancel_cycle(cycle)
    return suspended_lines
