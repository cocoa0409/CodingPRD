"""Business-logic services: calculations, inventory math, and cascades.

Every rule traces to PRD §3 / SCAFFOLD §1.3.
"""

from decimal import Decimal

from db import store
from util import round_half_up, pct_of, touch

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
TIER_SURGE = {"LOW": 100, "MID": 115, "HIGH": 130}
PEAK_BONUS = 10
STAFF_THROUGHPUT = 40
PEAK_STAFF_BONUS = 1


# ---------------------------------------------------------------------------
# event_day_item_pricing (PRD §3.4, SCAFFOLD §1.3)
#   surge_pct = TIER_SURGE[tier] + (PEAK_BONUS if peak_window else 0)
#   raw = base_price_cents * (multiplier_pct/100) * (surge_pct/100)
#   price_cents = round_half_up(raw)  -- single round at the very end
# ---------------------------------------------------------------------------
def compute_item_price(product, event, stand):
    surge_pct = TIER_SURGE[stand["demand_tier"]]
    if event["peak_window"]:
        surge_pct += PEAK_BONUS
    raw = (
        Decimal(product["base_price_cents"])
        * (Decimal(event["event_multiplier_pct"]) / Decimal(100))
        * (Decimal(surge_pct) / Decimal(100))
    )
    return round_half_up(raw)


def recompute_menu_prices_for_event(event):
    """Recompute price_cents for every MenuItem under every Stand of the event.

    Each touched MenuItem is itself a mutation (PRD §2.5): updated_at/version bump.
    """
    stands_by_id = {
        s["id"]: s for s in store.stands.values() if s["event_id"] == event["id"]
    }
    for mi in store.menu_items.values():
        stand = stands_by_id.get(mi["stand_id"])
        if stand is None:
            continue
        product = store.products.get(mi["product_id"])
        if product is None:
            continue
        new_price = compute_item_price(product, event, stand)
        mi["price_cents"] = new_price
        touch(mi)


# ---------------------------------------------------------------------------
# required_staffing (PRD §3.7, SCAFFOLD §1.3)
#   base = ceil(expected_orders_per_hour / STAFF_THROUGHPUT)
#   required_staff = base + (PEAK_STAFF_BONUS if peak_window else 0)
# ---------------------------------------------------------------------------
def compute_required_staff(stand, event):
    eph = stand["expected_orders_per_hour"]
    base = -(-eph // STAFF_THROUGHPUT)  # ceiling division for non-negative ints
    bonus = PEAK_STAFF_BONUS if event["peak_window"] else 0
    return base + bonus


def recompute_open_stands_staffing(event):
    """Recompute required_staff for every OPEN stand of the event (PRD §3.3)."""
    for s in store.stands.values():
        if s["event_id"] == event["id"] and s["status"] == "OPEN":
            s["required_staff"] = compute_required_staff(s, event)
            touch(s)


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------
def active_lots(stand_id, product_id):
    """ACTIVE lots of (stand, product), oldest created_at first (FIFO)."""
    lots = [
        lot for lot in store.inventory_lots.values()
        if lot["stand_id"] == stand_id
        and lot["product_id"] == product_id
        and lot["status"] == "ACTIVE"
    ]
    lots.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
    return lots


def on_hand(stand_id, product_id):
    """Summed remaining_qty across ACTIVE lots of (stand, product)."""
    return sum(lot["remaining_qty"] for lot in active_lots(stand_id, product_id))


def debit_fifo(stand_id, product_id, qty):
    """Debit `qty` units across ACTIVE lots oldest-first. Lots reaching 0 -> DEPLETED.

    Returns a list of (lot, units_taken) pairs (for weighted-average costing on
    transfer). Caller must have verified on_hand >= qty first.
    """
    taken = []
    remaining = qty
    for lot in active_lots(stand_id, product_id):
        if remaining <= 0:
            break
        take = min(lot["remaining_qty"], remaining)
        if take <= 0:
            continue
        lot["remaining_qty"] -= take
        remaining -= take
        taken.append((lot, take))
        if lot["remaining_qty"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    return taken


def weighted_avg_cost_of_taken(taken):
    """Weighted-average unit cost (round_half_up) over (lot, units) debits.

    Used to set the unit_cost_cents of the destination/compensation lot created
    by a transfer (PRD §3.5).
    """
    total_units = sum(units for _lot, units in taken)
    if total_units == 0:
        return 0
    total_cost = sum(Decimal(lot["unit_cost_cents"]) * units for lot, units in taken)
    return round_half_up(total_cost / Decimal(total_units))


# ---------------------------------------------------------------------------
# order_totals (PRD §3.8, SCAFFOLD §1.3)
#   Per line: line_subtotal = unit_price * qty
#             line_fee = round_half_up(line_subtotal * service_fee_pct / 100)
#   subtotal = sum(line_subtotal)
#   service_fee = sum(line_fee)  -- round PER LINE, then sum
#   total = subtotal + service_fee
# ---------------------------------------------------------------------------
def lines_of_order(order_id):
    lines = [ln for ln in store.order_lines.values() if ln["order_id"] == order_id]
    lines.sort(key=lambda ln: (ln["created_at"], ln["_seq"]))
    return lines


def compute_line_fields(line, service_fee_pct):
    line["line_subtotal_cents"] = line["unit_price_cents"] * line["qty"]
    line["line_fee_cents"] = pct_of(line["line_subtotal_cents"], service_fee_pct)


def recompute_order_totals(order, venue):
    service_fee_pct = venue["service_fee_pct"]
    subtotal = 0
    fee = 0
    for line in lines_of_order(order["id"]):
        compute_line_fields(line, service_fee_pct)
        subtotal += line["line_subtotal_cents"]
        fee += line["line_fee_cents"]
    order["subtotal_cents"] = subtotal
    order["service_fee_cents"] = fee
    order["total_cents"] = subtotal + fee


# ---------------------------------------------------------------------------
# spoilage_valuation (PRD §3.6, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def candidate_waste_lots(stand_id, product_id):
    """ACTIVE + EXPIRED lots of (stand, product), oldest created_at first."""
    lots = [
        lot for lot in store.inventory_lots.values()
        if lot["stand_id"] == stand_id
        and lot["product_id"] == product_id
        and lot["status"] in ("ACTIVE", "EXPIRED")
    ]
    lots.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
    return lots


def cost_fifo(stand_id, product_id, qty):
    """FIFO cost: walk candidate lots oldest-first, sum units*lot.unit_cost_cents
    until `qty` units are costed. Costing only; does not mutate lots."""
    remaining = qty
    cost = 0
    for lot in candidate_waste_lots(stand_id, product_id):
        if remaining <= 0:
            break
        take = min(lot["remaining_qty"], remaining)
        if take <= 0:
            continue
        cost += take * lot["unit_cost_cents"]
        remaining -= take
    # If candidate on-hand is short, cost whatever was available (qty validation
    # is the caller's responsibility for order/transfer flows).
    return cost


def cost_weighted_avg(stand_id, product_id, qty):
    """WEIGHTED_AVG cost: blended unit cost across candidate lots' remaining qty,
    rounded half-up, times qty (PRD §3.6)."""
    lots = candidate_waste_lots(stand_id, product_id)
    total_units = sum(lot["remaining_qty"] for lot in lots)
    if total_units == 0:
        return 0
    total = sum(Decimal(lot["remaining_qty"]) * lot["unit_cost_cents"] for lot in lots)
    wavg = round_half_up(total / Decimal(total_units))
    return qty * wavg


def compute_waste_cost(venue, stand_id, product_id, qty):
    if venue["spoilage_valuation"] == "FIFO":
        return cost_fifo(stand_id, product_id, qty)
    return cost_weighted_avg(stand_id, product_id, qty)


# ---------------------------------------------------------------------------
# revenue_share_settlement (PRD §3.9, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_revenue_share(gross, waste, venue):
    if venue["share_basis"] == "GROSS":
        base = gross
    else:  # NET
        base = max(0, gross - waste)
    venue_share = pct_of(base, venue["venue_share_pct"])
    operator_net = gross - venue_share
    return venue_share, operator_net
