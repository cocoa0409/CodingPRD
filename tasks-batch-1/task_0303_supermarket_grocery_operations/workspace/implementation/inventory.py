"""Inventory rollup, reorder flag, FEFO depletion, lot write-off helpers."""
from common import round_half_up
from clock import clock
from db import db

# Lot statuses counted toward on-hand
ON_HAND_STATES = ("ACTIVE", "QUARANTINED")


def lot_value(product, lot):
    """Book value of a lot's remaining quantity at its own unit cost."""
    rem = lot["remaining_qty"]
    if product["sell_by_weight"]:
        return round_half_up(rem * lot["unit_cost_cents"], 1000)
    return rem * lot["unit_cost_cents"]


def lots_of_product(product_id):
    return [l for l in db.inventory_lots.values() if l["product_id"] == product_id]


def product_inventory_rollup(product):
    """Recompute on_hand_qty + on_hand_value_cents from ACTIVE/QUARANTINED lots,
    then recompute the reorder flag. Does NOT bump the product version — callers
    that also affect the product through receive/price-plan create bump version
    explicitly per PRD §2.6."""
    lots = [l for l in lots_of_product(product["id"]) if l["status"] in ON_HAND_STATES]
    on_hand_qty = sum(l["remaining_qty"] for l in lots)
    on_hand_value = 0
    for l in lots:
        on_hand_value += lot_value(product, l)
    product["on_hand_qty"] = on_hand_qty
    product["on_hand_value_cents"] = on_hand_value
    reorder_flag(product)


def reorder_flag(product):
    """reorder_flagged true exactly when on_hand_qty <= reorder_point_qty (inclusive)."""
    product["reorder_flagged"] = product["on_hand_qty"] <= product["reorder_point_qty"]


def fefo_eligible_lots(product_id):
    """ACTIVE lots whose expiration is null or strictly after the clock, ordered
    FEFO: expiration soonest first (nulls last), then created_at ASC."""
    now = clock.now()
    eligible = []
    for l in lots_of_product(product_id):
        if l["status"] != "ACTIVE":
            continue
        exp = l.get("_expiration_dt")
        if exp is not None and not (exp > now):
            continue
        eligible.append(l)

    def sort_key(l):
        exp = l.get("_expiration_dt")
        # nulls last: tag 1 for null so they sort after dated lots
        null_tag = 1 if exp is None else 0
        exp_key = exp if exp is not None else now  # placeholder; null_tag dominates
        return (null_tag, exp_key, l["created_at"], l.get("_seq", 0))

    eligible.sort(key=sort_key)
    return eligible


def fefo_available(product_id):
    """Total demand-satisfiable quantity across FEFO-eligible lots."""
    return sum(l["remaining_qty"] for l in fefo_eligible_lots(product_id))


def fefo_deplete(product, demand):
    """Deplete `demand` units from FEFO-eligible lots. Returns accumulated cogs.
    Caller MUST verify fefo_available >= demand first (atomicity)."""
    remaining = demand
    cogs = 0
    for lot in fefo_eligible_lots(product["id"]):
        if remaining <= 0:
            break
        take = min(lot["remaining_qty"], remaining)
        if take <= 0:
            continue
        lot["remaining_qty"] -= take
        remaining -= take
        if product["sell_by_weight"]:
            cogs += round_half_up(take * lot["unit_cost_cents"], 1000)
        else:
            cogs += take * lot["unit_cost_cents"]
        if lot["remaining_qty"] == 0:
            lot["status"] = "DEPLETED"
    return cogs
