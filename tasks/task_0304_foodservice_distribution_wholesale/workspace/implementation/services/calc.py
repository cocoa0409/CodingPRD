"""Calculation engine: allocation, pricing, totals, replenishment, return credit.

All monetary values are integer cents; all quantities are integer splits. The
rounding direction for each step is taken verbatim from PRD §2.6 and §3:
  - tier and case counts: round DOWN (floor)
  - per-split price derived from a case price: round UP (ceil)
  - per-split delivered value and restocking fees: round HALF UP
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from services.clocks import parse_iso


RESTOCK_FEE_RATE = Decimal("0.15")  # 15% restocking fee on OVERAGE returns (SCAFFOLD §1.3)


def _round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to a whole integer."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# --- Inventory allocation (FEFO waterfall) -----------------------------------

def _candidate_lots(product, warehouse_id, delivery_dt):
    """Return FEFO-ordered candidate lots for a product at a warehouse.

    Candidate = lot at warehouse_id with available (on_hand - reserved) > 0.
    For a perishable product, a lot is a candidate only when expires_on is
    strictly after the delivery date (half-open freshness window). Perishable
    lots are ordered by expires_on ASC then created_at ASC; non-perishable lots
    by created_at ASC. (PRD §3.4, SCAFFOLD allocate_inventory.)
    """
    perishable = product["perishable"]
    lots = []
    for lot in db.inventory_lots.values():
        if lot["product_id"] != product["id"]:
            continue
        if lot["warehouse_id"] != warehouse_id:
            continue
        available = lot["on_hand_splits"] - lot["reserved_splits"]
        if available <= 0:
            continue
        if perishable:
            exp = lot.get("expires_on")
            if exp is None:
                # No expiration recorded: cannot prove freshness window contains
                # delivery instant -> excluded for a perishable product.
                continue
            exp_dt = parse_iso(exp, "expires_on")
            if not (exp_dt > delivery_dt):
                continue
        lots.append(lot)

    if perishable:
        lots.sort(key=lambda l: (parse_iso(l["expires_on"], "expires_on"), l["created_at"]))
    else:
        lots.sort(key=lambda l: l["created_at"])
    return lots


def _has_eligible_perishable_lot(product, warehouse_id, delivery_dt):
    """True if at least one candidate lot exists whose freshness window contains
    the delivery instant (used for the ERR_LOT_EXPIRES_BEFORE_DELIVERY guard)."""
    return len(_candidate_lots(product, warehouse_id, delivery_dt)) > 0


def allocate_line(line, product, warehouse_id, delivery_dt, products_by_id):
    """Allocate inventory for one OPEN order line (FEFO waterfall + substitute).

    Mutates the line's allocated_splits/short_splits/substituted/
    fulfilled_product_id/line_status, and increases reserved_splits on each lot
    drawn from. Returns nothing; caller persists.
    """
    uom = line["uom"]
    splits_per_case = product["splits_per_case"]
    if uom == "CASE":
        need_splits = line["ordered_qty"] * splits_per_case
    else:
        need_splits = line["ordered_qty"]

    allocated = 0
    primary_taken = 0
    need_remaining = need_splits
    # Exact per-lot allocation map {lot_id: splits} so cancel/POD can release or
    # consume from precisely the lots this line drew from.
    lot_alloc = {}

    # Primary product FEFO draw.
    for lot in _candidate_lots(product, warehouse_id, delivery_dt):
        if need_remaining <= 0:
            break
        available = lot["on_hand_splits"] - lot["reserved_splits"]
        take = min(need_remaining, available)
        if take <= 0:
            continue
        lot["reserved_splits"] += take
        allocated += take
        primary_taken += take
        need_remaining -= take
        lot_alloc[lot["id"]] = lot_alloc.get(lot["id"], 0) + take

    substituted = False
    sub_id = product.get("substitute_product_id")
    if need_remaining > 0 and sub_id:
        sub_product = products_by_id.get(sub_id)
        if sub_product is not None:
            for lot in _candidate_lots(sub_product, warehouse_id, delivery_dt):
                if need_remaining <= 0:
                    break
                available = lot["on_hand_splits"] - lot["reserved_splits"]
                take = min(need_remaining, available)
                if take <= 0:
                    continue
                lot["reserved_splits"] += take
                allocated += take
                need_remaining -= take
                substituted = True
                lot_alloc[lot["id"]] = lot_alloc.get(lot["id"], 0) + take

    line["_lot_allocations"] = lot_alloc
    line["allocated_splits"] = allocated
    line["short_splits"] = need_remaining
    line["substituted"] = substituted
    line["line_status"] = "ALLOCATED" if allocated == need_splits else "SHORTED"
    # fulfilled_product_id = substitute when filled entirely from substitute
    # (primary took nothing), else the originally requested product.
    if substituted and primary_taken == 0:
        line["fulfilled_product_id"] = sub_id
    else:
        line["fulfilled_product_id"] = line["product_id"]


# --- Line pricing (tiered) ---------------------------------------------------

def _tiers_for_product(product_id):
    tiers = [t for t in db.price_tiers.values() if t["product_id"] == product_id]
    return tiers


def price_line(line, fulfilled_product):
    """Compute unit_case_price_cents and extended_price_cents for one line.

    Tier chosen on ORDERED case-equivalents; charge computed on ALLOCATED
    quantity (PRD §3.4 pricing).
    """
    splits_per_case = fulfilled_product["splits_per_case"]
    uom = line["uom"]
    if uom == "CASE":
        ordered_splits = line["ordered_qty"] * splits_per_case
    else:
        ordered_splits = line["ordered_qty"]

    tier_key_cases = ordered_splits // splits_per_case  # floor
    if tier_key_cases < 1:
        tier_key_cases = 1

    tier = _select_tier_with_tiebreak(fulfilled_product["id"], tier_key_cases)
    unit_case_price = tier["case_price_cents"] if tier is not None else 0

    priced_splits = line["allocated_splits"]
    full_cases = priced_splits // splits_per_case  # floor
    residual_splits = priced_splits - full_cases * splits_per_case
    # Each residual split priced at ceil(case_price / splits_per_case).
    split_unit = -(-unit_case_price // splits_per_case)  # ceil division
    extended = full_cases * unit_case_price + residual_splits * split_unit

    line["unit_case_price_cents"] = unit_case_price
    line["extended_price_cents"] = extended


def _select_tier_with_tiebreak(product_id, tier_key_cases):
    """Greatest min_cases <= key; tie-break created_at ASC."""
    candidates = [t for t in _tiers_for_product(product_id)
                  if t["min_cases"] <= tier_key_cases]
    if not candidates:
        return None
    # Sort by min_cases DESC, then created_at ASC; pick first.
    candidates.sort(key=lambda t: (-t["min_cases"], t["created_at"]))
    return candidates[0]


# --- Order totals ------------------------------------------------------------

def compute_order_totals(order, lines, customer):
    """Recompute goods_subtotal_cents, split_fee_total_cents, order_total_cents.

    goods_subtotal = sum of extended_price_cents over non-removed lines.
    split_fee_total = customer.split_fee_cents * count(SPLIT lines that are not
        removed and allocated > 0 splits).
    order_total = goods_subtotal + split_fee_total. (PRD §3.4 totals.)
    """
    goods = 0
    fee_count = 0
    for line in lines:
        if line["line_status"] == "REMOVED":
            continue
        goods += line["extended_price_cents"]
        if line["uom"] == "SPLIT" and line["allocated_splits"] > 0:
            fee_count += 1
    split_fee_total = customer["split_fee_cents"] * fee_count
    order["goods_subtotal_cents"] = goods
    order["split_fee_total_cents"] = split_fee_total
    order["order_total_cents"] = goods + split_fee_total


# --- Par-based replenishment -------------------------------------------------

def replenishment_suggestion(item, product):
    """Compute (suggested_uom, suggested_qty) for one OrderGuideItem, or None
    when the item is already at/over par (deficit zero). (PRD §3.2.)"""
    deficit = max(0, item["par_level_splits"] - item["on_hand_splits"])
    if deficit == 0:
        return None
    splits_per_case = product["splits_per_case"]
    if not product["split_allowed"]:
        # Round UP to whole cases.
        qty = -(-deficit // splits_per_case)  # ceil division
        return {"suggested_uom": "CASE", "suggested_qty": qty}
    return {"suggested_uom": "SPLIT", "suggested_qty": deficit}


# --- Return credit -----------------------------------------------------------

def compute_return_credit(ret, line, fulfilled_product):
    """Compute restock_fee_cents and credit_amount_cents for a return (PRD §3.7).

    per-split delivered value = round_half_up(extended_price / allocated_splits)
    returned_goods = per-split value * return_splits
    restock_fee = round_half_up(returned_goods * 0.15) for OVERAGE, else 0
    credit_amount = returned_goods - restock_fee
    """
    allocated = line["allocated_splits"]
    delivered_split_value = _round_half_up(line["extended_price_cents"], allocated)
    returned_goods = delivered_split_value * ret["return_splits"]
    if ret["reason"] == "OVERAGE":
        restock_fee = int((Decimal(returned_goods) * RESTOCK_FEE_RATE).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        restock_fee = 0
    ret["restock_fee_cents"] = restock_fee
    ret["credit_amount_cents"] = returned_goods - restock_fee
