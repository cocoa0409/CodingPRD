"""Inventory + ledger recompute logic and the calculation rules (SCAFFOLD §1.3).

These functions recompute derived quantities and write them back onto the stored
records. Each *cascade* that changes a resource also calls helpers.touch() on it
(refreshes updated_at, bumps version) per PRD §2.10.
"""
from helpers import round_kg, clamp_kg, round_cents, D, touch
from db import store


# --------------------------------------------------------------------------
# Green lot accounting (PRD §2.7, calc green_reorder_status)
# --------------------------------------------------------------------------
def recompute_green_lot(lot, bump=False):
    """Recompute on_hand/reserved/available/reorder_status for a green lot.

    on_hand_kg  = received_kg - sum(actual_green_kg for batches in
                  {ROASTING, COOLING, COMPLETED}), 3dp HALF_UP, clamp >=0
    reserved_kg = sum(planned_green_kg for batches in PLANNED), 3dp HALF_UP
    available_kg = on_hand_kg - reserved_kg, 3dp HALF_UP, clamp >=0
    reorder_status = BELOW_PAR if available_kg < par_level_kg else OK
    """
    consumed = D(0)
    reserved = D(0)
    for b in store.roast_batches.values():
        if b["green_lot_id"] != lot["id"]:
            continue
        st = b["status"]
        if st in ("ROASTING", "COOLING", "COMPLETED"):
            if b.get("actual_green_kg") is not None:
                consumed += D(b["actual_green_kg"])
        elif st == "PLANNED":
            reserved += D(b["planned_green_kg"])

    on_hand = clamp_kg(D(lot["received_kg"]) - consumed)
    reserved_kg = round_kg(reserved)
    available = clamp_kg(D(on_hand) - D(reserved_kg))

    changed = (
        lot.get("on_hand_kg") != on_hand
        or lot.get("reserved_kg") != reserved_kg
        or lot.get("available_kg") != available
    )
    lot["on_hand_kg"] = on_hand
    lot["reserved_kg"] = reserved_kg
    lot["available_kg"] = available
    # strict < triggers BELOW_PAR; == par is OK
    lot["reorder_status"] = "BELOW_PAR" if D(available) < D(lot["par_level_kg"]) else "OK"
    if bump and changed:
        touch(lot)


# --------------------------------------------------------------------------
# Roasted lot accounting (PRD §2.8, calc roasted_lot_availability)
# --------------------------------------------------------------------------
def recompute_roasted_lot(lot, bump=False):
    """reserved_kg = sum(allocated_kg for fulfillments in {RESERVED, SHIPPED})
    on_hand_kg  = produced_kg - sum(allocated_kg for fulfillments SHIPPED), clamp
    available_kg = produced_kg - reserved_kg, clamp
    """
    reserved = D(0)
    shipped = D(0)
    for f in store.fulfillments.values():
        if f["roasted_lot_id"] != lot["id"]:
            continue
        if f["status"] in ("RESERVED", "SHIPPED"):
            reserved += D(f["allocated_kg"])
        if f["status"] == "SHIPPED":
            shipped += D(f["allocated_kg"])

    produced = D(lot["produced_kg"])
    reserved_kg = round_kg(reserved)
    on_hand = clamp_kg(produced - shipped)
    available = clamp_kg(produced - D(reserved_kg))

    changed = (
        lot.get("reserved_kg") != reserved_kg
        or lot.get("on_hand_kg") != on_hand
        or lot.get("available_kg") != available
    )
    lot["reserved_kg"] = reserved_kg
    lot["on_hand_kg"] = on_hand
    lot["available_kg"] = available
    if bump and changed:
        touch(lot)


# --------------------------------------------------------------------------
# Account outstanding balance (PRD §2.9, calc account_outstanding_balance)
# --------------------------------------------------------------------------
def posted_balance(account):
    """Sum of amount_due_cents over invoices in {ISSUED, PARTIALLY_PAID, OVERDUE}."""
    total = 0
    for inv in store.invoices.values():
        if inv["account_id"] != account["id"]:
            continue
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
            total += invoice_amount_due(inv)
    return total


def recompute_account_balance(account, bump=False):
    new_balance = posted_balance(account)
    changed = account.get("outstanding_balance_cents") != new_balance
    account["outstanding_balance_cents"] = new_balance
    if bump and changed:
        touch(account)


# --------------------------------------------------------------------------
# Invoice paid / amount_due (PRD §3.6)
# --------------------------------------------------------------------------
def invoice_paid(invoice):
    total = 0
    for p in store.payments.values():
        if p["invoice_id"] == invoice["id"] and p["status"] == "CLEARED":
            total += p["amount_cents"]
    return total


def invoice_amount_due(invoice):
    due = invoice["amount_cents"] - invoice_paid(invoice)
    return due if due > 0 else 0


# --------------------------------------------------------------------------
# Order pricing (PRD §3.4, calc order_pricing)
# Round each line to integer cents FIRST, then sum, then discount on subtotal.
# --------------------------------------------------------------------------
def price_order(lines, tier):
    """lines: list of {product, qty_kg}. tier: PriceTier record.

    Returns (subtotal_cents, discount_cents, total_cents).
    """
    subtotal = 0
    for line in lines:
        product = line["product"]
        per_line = round_cents(D(line["qty_kg"]) * D(product["base_price_cents_per_kg"]))
        subtotal += per_line
    discount = round_cents(D(subtotal) * D(tier["discount_bps"]) / D(10000))
    total = subtotal - discount
    return subtotal, discount, total
