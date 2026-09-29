"""Conservation ledgers and derived-field recomputation (PRD 2.8, 2.9, 3.x)."""

from decimal import Decimal

import calc
from calc import dec, rhu
from db import ordered, store, touch

LIVE_LINE_STATUSES = ("RESERVED", "CUT", "SHIPPED")
CREDIT_RESERVED_ORDER_STATUSES = ("SUBMITTED", "ALLOCATED", "BACKORDERED", "CUT")


# ---- lookups --------------------------------------------------------------

def rolls_of_dye_lot(dye_lot_id):
    return ordered([r for r in store.roll_goods.values() if r["dye_lot_id"] == dye_lot_id])


def rolls_of_run(run_id):
    return ordered(
        [r for r in store.roll_goods.values() if r["production_run_id"] == run_id]
    )


def lines_of_roll(roll_id):
    return ordered(
        [a for a in store.cut_allocations.values() if a["roll_good_id"] == roll_id]
    )


def lines_of_order(order_id):
    return ordered(
        [a for a in store.cut_allocations.values() if a["cut_order_id"] == order_id]
    )


def orders_of_account(account_id):
    return ordered([o for o in store.cut_orders.values() if o["account_id"] == account_id])


def orders_of_style(style_id):
    return ordered([o for o in store.cut_orders.values() if o["style_id"] == style_id])


def runs_of_style(style_id):
    return ordered([r for r in store.runs.values() if r["style_id"] == style_id])


# ---- calculation 2: polymer mass buckets ---------------------------------

def recompute_polymer_status(lot):
    """DEPLETED exactly when available_kg == 0; the transition is bidirectional."""
    before = lot["status"]
    lot["status"] = "DEPLETED" if dec(lot["available_kg"]) == 0 else "AVAILABLE"
    if lot["status"] != before:
        touch(lot)


def move_polymer(lot, source, target, kg):
    """Shift ``kg`` between two buckets of a polymer lot, keeping the identity."""
    amount = rhu(kg, 3)
    if amount == 0:
        return
    lot[source] = float(rhu(dec(lot[source]) - amount, 3))
    lot[target] = float(rhu(dec(lot[target]) + amount, 3))
    if dec(lot[source]) < 0:
        lot[source] = 0.0
    touch(lot)
    recompute_polymer_status(lot)


# ---- calculation 12: roll-good yardage ledger + inventory status ----------

def recompute_roll(roll):
    before = (roll["available_yards"], roll["inventory_status"])
    lines = lines_of_roll(roll["id"])
    committed = Decimal(0)
    has_reserved = False
    for line in lines:
        if line["status"] in LIVE_LINE_STATUSES:
            committed += dec(line["yards"])
        if line["status"] == "RESERVED":
            has_reserved = True

    if roll["inventory_status"] == "SCRAPPED":
        available = Decimal("0.0")
    else:
        available = rhu(
            dec(roll["initial_yards"]) - committed - dec(roll.get("_split_yards", 0.0)), 1
        )
        if available < 0:
            available = Decimal("0.0")
    roll["available_yards"] = float(available)

    inventory = roll["inventory_status"]
    if inventory not in ("SCRAPPED", "DEPLETED"):
        if roll["qa_status"] == "PASSED":
            if available == 0 and has_reserved:
                roll["inventory_status"] = "COMMITTED"
            elif available > 0:
                roll["inventory_status"] = "AVAILABLE"
        elif roll["qa_status"] in ("PENDING", "HELD"):
            roll["inventory_status"] = "IN_PROCESS"

    if (roll["available_yards"], roll["inventory_status"]) != before:
        touch(roll)
    return roll


# ---- calculation 9: dye-lot uncommitted yardage (two variants) ------------

def recompute_dye_lot_yards(lot):
    before = (
        lot["uncommitted_yards"],
        lot["shipped_basis_uncommitted_yards"],
        lot["status"],
    )
    base = dec(lot["dyed_yards"]) - dec(lot["scrapped_yards"])
    committed = Decimal(0)
    shipped = Decimal(0)
    for roll in rolls_of_dye_lot(lot["id"]):
        if roll["inventory_status"] == "SCRAPPED":
            continue
        for line in lines_of_roll(roll["id"]):
            if line["status"] in LIVE_LINE_STATUSES:
                committed += dec(line["yards"])
            if line["status"] == "SHIPPED":
                shipped += dec(line["yards"])
    uncommitted = rhu(base - committed, 1)
    lot["uncommitted_yards"] = float(uncommitted)
    lot["shipped_basis_uncommitted_yards"] = float(rhu(base - shipped, 1))
    if lot["status"] == "APPROVED" and uncommitted <= 0:
        lot["status"] = "EXHAUSTED"
    if (
        lot["uncommitted_yards"],
        lot["shipped_basis_uncommitted_yards"],
        lot["status"],
    ) != before:
        touch(lot)
    return lot


def recompute_dye_lots_for_lines(lines):
    seen = set()
    for line in lines:
        roll = store.roll_goods.get(line["roll_good_id"])
        if not roll or not roll.get("dye_lot_id"):
            continue
        if roll["dye_lot_id"] in seen:
            continue
        seen.add(roll["dye_lot_id"])
        lot = store.dye_lots.get(roll["dye_lot_id"])
        if lot:
            recompute_dye_lot_yards(lot)


# ---- calculations 17 + 18: line charges and settlement -------------------

def recompute_order_financials(order):
    before = (
        order["allocated_yards"],
        order["gross_cents"],
        order["freight_cents"],
        order["remnant_credit_cents"],
        order["net_invoice_cents"],
    )
    style = store.styles.get(order["style_id"])
    price = style["list_price_cents_per_yard"] if style else 0

    live = [a for a in lines_of_order(order["id"]) if a["status"] in LIVE_LINE_STATUSES]

    allocated = rhu(sum((dec(a["yards"]) for a in live), Decimal(0)), 1)
    order["allocated_yards"] = float(allocated)

    gross = 0
    any_remnant = False
    for line in live:
        value = calc.line_cents(
            line["yards"], price, line["shade_band"], bool(line["from_remnant"])
        )
        if line["line_cents"] != value:
            line["line_cents"] = value
            touch(line)
        gross += value
        if line["from_remnant"]:
            any_remnant = True

    if not live:
        # Zero-line guard: no live line means no freight and no remnant credit.
        order["gross_cents"] = 0
        order["freight_cents"] = 0
        order["remnant_credit_cents"] = 0
        order["net_invoice_cents"] = 0
    else:
        freight = calc.freight_cents_for(gross)
        remnant = calc.remnant_credit_cents_for(gross) if any_remnant else 0
        order["gross_cents"] = gross
        order["freight_cents"] = freight
        order["remnant_credit_cents"] = remnant
        order["net_invoice_cents"] = gross + freight - remnant

    after = (
        order["allocated_yards"],
        order["gross_cents"],
        order["freight_cents"],
        order["remnant_credit_cents"],
        order["net_invoice_cents"],
    )
    if after != before:
        touch(order)
    return order


# ---- calculation 16: account credit ledger -------------------------------

def account_exposure(account_id):
    used = 0
    for order in orders_of_account(account_id):
        if order["status"] in CREDIT_RESERVED_ORDER_STATUSES:
            used += int(order["reserved_credit_cents"])
        elif order["status"] == "SHIPPED":
            used += int(order["net_invoice_cents"])
    return used


def recompute_account(account):
    before = (account["credit_used_cents"], account["status"])
    used = account_exposure(account["id"])
    account["credit_used_cents"] = used
    if account["status"] != "CLOSED":
        account["status"] = (
            "CREDIT_HOLD" if used >= int(account["credit_limit_cents"]) else "ACTIVE"
        )
    if (account["credit_used_cents"], account["status"]) != before:
        touch(account)
    return account


# ---- calculation 11: style backorder posture -----------------------------

def recompute_style_posture(style):
    before = (style["open_backorder_yards"], style["replenishment_flag"])
    total = Decimal(0)
    for order in orders_of_style(style["id"]):
        if order["status"] in ("SUBMITTED", "BACKORDERED"):
            total += dec(order["requested_yards"]) - dec(order["allocated_yards"])
    open_yards = rhu(total, 1)
    if open_yards < 0:
        open_yards = Decimal("0.0")
    style["open_backorder_yards"] = float(open_yards)
    style["replenishment_flag"] = (
        "REPLENISH_REQUIRED"
        if open_yards >= calc.STYLE_BACKORDER_ALERT_YARDS
        else "NONE"
    )
    if (style["open_backorder_yards"], style["replenishment_flag"]) != before:
        touch(style)
    return style
