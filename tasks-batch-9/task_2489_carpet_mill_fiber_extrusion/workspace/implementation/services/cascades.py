"""Multi-hop cascades across the mill graph (PRD 2.9, 3.3, 3.6, 3.7, 3.9)."""

from decimal import Decimal

import calc
from calc import dec, rhu
from db import ordered, store, touch
from services import compliance, ledgers


# ---- roll-good scrapping (shared by QA SCRAP and the rejection cascade) ----

def _shipped_yards_off(roll):
    total = Decimal(0)
    for line in ledgers.lines_of_roll(roll["id"]):
        if line["status"] == "SHIPPED":
            total += dec(line["yards"])
    return total


def scrap_charge(roll):
    """initial_yards less the yards already shipped off the roll."""
    charge = rhu(dec(roll["initial_yards"]) - _shipped_yards_off(roll), 1)
    if charge < 0:
        charge = Decimal("0.0")
    return charge


def scrap_roll(roll):
    """Set the terminal QA/inventory pair, charge the lot and void RESERVED lines."""
    lot = store.dye_lots.get(roll.get("dye_lot_id")) if roll.get("dye_lot_id") else None
    if lot is not None:
        charge = scrap_charge(roll)
        if charge != 0:
            lot["scrapped_yards"] = float(rhu(dec(lot["scrapped_yards"]) + charge, 1))
            touch(lot)

    roll["qa_status"] = "FAILED"
    roll["inventory_status"] = "SCRAPPED"
    roll["available_yards"] = 0.0
    touch(roll)

    voided = []
    for line in ledgers.lines_of_roll(roll["id"]):
        if line["status"] == "RESERVED":
            line["status"] = "VOIDED"
            touch(line)
            voided.append(line)
    return voided


def reconcile_orders_of_lines(lines, backorder=False):
    """Recompute the orders behind ``lines``; optionally run the BACKORDERED hop."""
    order_ids = []
    for line in lines:
        if line["cut_order_id"] not in order_ids:
            order_ids.append(line["cut_order_id"])

    newly_backordered = []
    style_ids = []
    for order_id in order_ids:
        order = store.cut_orders.get(order_id)
        if not order:
            continue
        ledgers.recompute_order_financials(order)
        if (
            backorder
            and order["status"] == "ALLOCATED"
            and dec(order["allocated_yards"]) < dec(order["requested_yards"])
        ):
            order["status"] = "BACKORDERED"
            touch(order)
            newly_backordered.append(order)
        if order["style_id"] not in style_ids:
            style_ids.append(order["style_id"])

    for style_id in style_ids:
        style = store.styles.get(style_id)
        if style:
            ledgers.recompute_style_posture(style)
    return newly_backordered


# ---- dye-lot rejection: the five-hop cascade of PRD 3.6 --------------------

def reject_dye_lot(lot):
    lot["status"] = "REJECTED"
    touch(lot)

    voided = []
    for roll in ledgers.rolls_of_dye_lot(lot["id"]):
        if roll["inventory_status"] == "SCRAPPED":
            continue
        voided.extend(scrap_roll(roll))

    reconcile_orders_of_lines(voided, backorder=True)
    ledgers.recompute_dye_lot_yards(lot)
    return lot


# ---- style discontinuation: PRD 3.3 --------------------------------------

def discontinue_style(style):
    style["status"] = "RUNOUT"
    touch(style)

    touched_accounts = []
    for order in ledgers.orders_of_style(style["id"]):
        if order["order_type"] != "CUSTOM" or order["status"] != "SUBMITTED":
            continue
        release_order_lines(order)
        order["status"] = "CANCELLED"
        order["reserved_credit_cents"] = 0
        touch(order)
        ledgers.recompute_order_financials(order)
        if order["account_id"] not in touched_accounts:
            touched_accounts.append(order["account_id"])

    for account_id in touched_accounts:
        account = store.accounts.get(account_id)
        if account:
            ledgers.recompute_account(account)

    for run in ledgers.runs_of_style(style["id"]):
        if run["status"] in ("SCHEDULED", "HELD"):
            abort_run(run)

    ledgers.recompute_style_posture(style)
    return style


def abort_run(run):
    run["status"] = "ABORTED"
    touch(run)
    batch = store.fiber_batches.get(run.get("fiber_batch_id"))
    if batch is not None and batch["status"] == "ALLOCATED":
        batch["status"] = "RELEASED"
        touch(batch)
    return run


# ---- cut-order line release (cancellation and the discontinuation hop) -----

def release_order_lines(order):
    released = []
    for line in ledgers.lines_of_order(order["id"]):
        if line["status"] == "RESERVED":
            line["status"] = "RELEASED"
            touch(line)
            released.append(line)
    for line in released:
        roll = store.roll_goods.get(line["roll_good_id"])
        if roll:
            ledgers.recompute_roll(roll)
    ledgers.recompute_dye_lots_for_lines(released)
    return released


# ---- the logical clock: certificate lapse and its compliance cascade ------

def advance_clock(new_dt, new_raw):
    store.clock_dt = new_dt
    store.clock_raw = new_raw

    lapsed = []
    for cert in ordered(list(store.certifications.values())):
        if cert["status"] != "ACTIVE":
            continue
        if cert["_expires_dt"] <= new_dt:
            cert["status"] = "LAPSED"
            touch(cert)
            lapsed.append(cert)

    suspended_style_ids = []
    held_run_ids = []
    style_ids = []
    for cert in lapsed:
        if cert["style_id"] not in style_ids:
            style_ids.append(cert["style_id"])
    for style_id in style_ids:
        style = store.styles.get(style_id)
        if not style:
            continue
        held = compliance.suspend_style_if_uncertified(style)
        if held is not None:
            suspended_style_ids.append(style["id"])
            held_run_ids.extend(held)

    return {
        "current_utc": store.clock_raw,
        "lapsed_certification_ids": [c["id"] for c in lapsed],
        "suspended_style_ids": suspended_style_ids,
        "held_production_run_ids": held_run_ids,
    }


# ---- cutting: remnant splits and depletion (PRD 3.9) ---------------------

def resolve_roll_after_cut(roll):
    """Split a sub-threshold residual off as a remnant child, or deplete."""
    lines = ledgers.lines_of_roll(roll["id"])
    if any(line["status"] == "RESERVED" for line in lines):
        return None
    if roll["inventory_status"] in ("SCRAPPED", "DEPLETED"):
        return None

    residual = dec(roll["available_yards"])
    child = None
    if residual > 0 and residual < calc.REMNANT_THRESHOLD_YARDS:
        child = _mint_remnant(roll, residual)
        roll["_split_yards"] = float(rhu(dec(roll.get("_split_yards", 0.0)) + residual, 1))
        ledgers.recompute_roll(roll)
        roll["inventory_status"] = "DEPLETED"
        roll["available_yards"] = 0.0
        touch(roll)
    elif residual == 0:
        roll["inventory_status"] = "DEPLETED"
        touch(roll)
    return child


def _mint_remnant(parent, residual):
    from db import insert

    existing = [
        r for r in store.roll_goods.values() if r.get("parent_roll_id") == parent["id"]
    ]
    counter = len(existing) + 1
    yards = float(rhu(residual, 1))
    return insert(
        store.roll_goods,
        {
            "roll_number": "%s-R%d" % (parent["roll_number"], counter),
            "production_run_id": parent["production_run_id"],
            "dye_lot_id": parent.get("dye_lot_id"),
            "parent_roll_id": parent["id"],
            "width_ft": parent["width_ft"],
            "initial_yards": yards,
            "available_yards": yards,
            "shade_band": parent["shade_band"],
            "is_remnant": True,
            "qa_status": "PASSED",
            "inventory_status": "AVAILABLE",
            "_split_yards": 0.0,
        },
    )
