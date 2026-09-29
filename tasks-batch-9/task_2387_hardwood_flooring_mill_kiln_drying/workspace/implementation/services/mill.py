"""Shared state-machine side effects and derived-field reconciliation."""

from db import db, ordered, touch
from services import calc
from services.calc import D, rhu


# --------------------------------------------------------------------------
# Green board feet ledger (PRD 2.8)
# --------------------------------------------------------------------------
def allocated_receipts(charge_id):
    return [r for r in ordered(db.green_receipts)
            if r.get("kiln_charge_id") == charge_id and r.get("status") == "ALLOCATED"]


def ledger_receipts(charge_id):
    """The conserved green board-foot set of a charge (PRD 2.8)."""
    return [r for r in ordered(db.green_receipts)
            if r.get("kiln_charge_id") == charge_id
            and r.get("status") in ("ALLOCATED", "CONSUMED")]


def recompute_charge_volume(charge):
    """charged_green_bf and weighted_initial_moisture_pct from the ledger set."""
    receipts = ledger_receipts(charge["id"])
    total_bf, weighted = calc.weighted_initial_moisture(receipts)
    charge["charged_green_bf"] = total_bf
    charge["weighted_initial_moisture_pct"] = weighted


# --------------------------------------------------------------------------
# Chamber occupancy
# --------------------------------------------------------------------------
def chamber_window_conflict(chamber_id, candidate_start, candidate_blocked_until, exclude_charge_id=None):
    for charge in ordered(db.kiln_charges):
        if charge["kiln_chamber_id"] != chamber_id:
            continue
        if exclude_charge_id is not None and charge["id"] == exclude_charge_id:
            continue
        if charge["status"] not in calc.CHAMBER_OCCUPYING_STATUSES:
            continue
        if charge.get("planned_start_utc") is None or charge.get("blocked_until_utc") is None:
            continue
        if calc.windows_conflict(candidate_start, candidate_blocked_until,
                                charge["planned_start_utc"], charge["blocked_until_utc"]):
            return charge
    return None


def chamber_has_active_charge(chamber_id, exclude_charge_id=None):
    active = ("LOADED", "DRYING", "CONDITIONING", "REDRY")
    for charge in db.kiln_charges.values():
        if charge["kiln_chamber_id"] != chamber_id:
            continue
        if exclude_charge_id is not None and charge["id"] == exclude_charge_id:
            continue
        if charge["status"] in active:
            return True
    return False


def displace_overlapping_charges(redrying_charge):
    """Cascade of the REDRY window extension (PRD 3.5)."""
    for charge in ordered(db.kiln_charges):
        if charge["id"] == redrying_charge["id"]:
            continue
        if charge["kiln_chamber_id"] != redrying_charge["kiln_chamber_id"]:
            continue
        if charge["status"] != "SCHEDULED":
            continue
        if not calc.windows_conflict(charge["planned_start_utc"], charge["blocked_until_utc"],
                                     redrying_charge["planned_start_utc"],
                                     redrying_charge["blocked_until_utc"]):
            continue
        charge["status"] = "DISPLACED"
        charge["displaced_reason"] = (
            "Displaced by the extended redry window of kiln charge %s." % redrying_charge["id"]
        )
        for receipt in allocated_receipts(charge["id"]):
            receipt["status"] = "ACCEPTED"
            receipt["kiln_charge_id"] = None
            touch(receipt)
        charge["charged_green_bf"] = 0
        charge["weighted_initial_moisture_pct"] = None
        touch(charge)


# --------------------------------------------------------------------------
# Kiln-dry volume ledger on a charge
# --------------------------------------------------------------------------
def recompute_remaining_dry_bf(charge):
    if charge.get("dry_bf_out") is None:
        charge["remaining_dry_bf"] = None
        return
    drawn = sum((D(lot["input_dry_bf"]) for lot in db.flooring_lots.values()
                 if lot["kiln_charge_id"] == charge["id"] and lot["status"] != "VOIDED"),
                D(0))
    charge["remaining_dry_bf"] = rhu(D(charge["dry_bf_out"]) - drawn, 2)


# --------------------------------------------------------------------------
# Core stock reservations
# --------------------------------------------------------------------------
def recompute_reserved_square_feet(stock):
    total = sum((D(lot["reserved_core_sf"]) for lot in db.flooring_lots.values()
                 if lot.get("core_stock_id") == stock["id"]
                 and lot["status"] != "VOIDED"
                 and lot.get("reserved_core_sf") is not None),
                D(0))
    stock["reserved_square_feet"] = rhu(total, 2)


# --------------------------------------------------------------------------
# Byproduct ledger
# --------------------------------------------------------------------------
def recompute_sold_tons(batch):
    total = sum((D(sale["quantity_tons"]) for sale in db.byproduct_sales.values()
                 if sale["byproduct_batch_id"] == batch["id"]), D(0))
    batch["sold_tons"] = rhu(total, 2)


def lot_batches(lot_id):
    return [b for b in ordered(db.byproduct_batches) if b["flooring_lot_id"] == lot_id]


def lot_has_byproduct_sale(lot_id):
    batch_ids = {b["id"] for b in db.byproduct_batches.values() if b["flooring_lot_id"] == lot_id}
    if not batch_ids:
        return False
    return any(sale["byproduct_batch_id"] in batch_ids for sale in db.byproduct_sales.values())


# --------------------------------------------------------------------------
# Warranty reserve ledger and product line posture (PRD 2.8 / 3.9)
# --------------------------------------------------------------------------
def recompute_posture(line):
    line["warranty_balance_cents"] = int(line["warranty_funded_total_cents"]) - \
        int(line["warranty_committed_cents"])
    line["posture"] = calc.derive_posture(line["warranty_balance_cents"], line["freeze_override"])
    return line["posture"]


def hold_scheduled_prefinish_runs(line, reason):
    for run in ordered(db.prefinish_runs):
        if run.get("product_line_id") != line["id"]:
            continue
        if run["status"] != "SCHEDULED":
            continue
        run["status"] = "HELD"
        run["hold_reason"] = reason
        touch(run)
