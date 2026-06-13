"""Calculation rules (SCAFFOLD §1.3, PRD §3). All money is integer cents."""
from decimal import Decimal, ROUND_HALF_UP

# order_totals shipping tiers (PRD §3.2)
FREE_SHIP_LOW = 5000
FREE_SHIP_HIGH = 10000
SHIP_STANDARD = 999
SHIP_REDUCED = 499

# return_settlement store-credit bonus (PRD §3.8)
STORE_CREDIT_BONUS_BPS = 500

# customer_return_risk
HIGH_RISK_THRESHOLD = Decimal("0.5")


def round_half_up_int(numerator, denominator):
    """round_half_up(numerator / denominator) -> integer cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_4(numerator, denominator):
    """ratio rounded half up to 4 decimal places (as a float for JSON)."""
    if denominator == 0:
        return 0.0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def shipping_fee(discounted_subtotal_cents):
    if discounted_subtotal_cents < FREE_SHIP_LOW:
        return SHIP_STANDARD
    elif discounted_subtotal_cents < FREE_SHIP_HIGH:
        return SHIP_REDUCED
    return 0


def compute_order_totals(lines, promo_flat_cents):
    """Pinned evaluation order (PRD §3.2). `lines` is a list of order-line
    dicts each with unit_price_cents_snapshot, qty, tax_rate_bps_snapshot.

    Returns dict with subtotal_cents, discounted_subtotal_cents,
    tax_total_cents, shipping_fee_cents, grand_total_cents, and a map of
    order_line_id -> line_tax_cents.
    """
    # (1) line subtotals + subtotal
    subtotal = 0
    line_subtotals = {}
    for L in lines:
        ls = L["unit_price_cents_snapshot"] * L["qty"]
        line_subtotals[L["id"]] = ls
        subtotal += ls
    # (2) flat promo, floored at 0; drives the shipping tier and is captured base
    discounted_subtotal = max(0, subtotal - promo_flat_cents)
    # (3) per-line tax on FULL pre-discount line subtotal; round per line THEN sum
    line_tax = {}
    tax_total = 0
    for L in lines:
        ls = line_subtotals[L["id"]]
        lt = round_half_up_int(ls * L["tax_rate_bps_snapshot"], 10000)
        line_tax[L["id"]] = lt
        tax_total += lt
    # (4) tiered shipping selected from discounted_subtotal
    ship = shipping_fee(discounted_subtotal)
    # (5) grand total
    grand_total = discounted_subtotal + tax_total + ship
    return {
        "subtotal_cents": subtotal,
        "discounted_subtotal_cents": discounted_subtotal,
        "tax_total_cents": tax_total,
        "shipping_fee_cents": ship,
        "grand_total_cents": grand_total,
        "line_tax": line_tax,
    }


def compute_return_settlement(rma, return_lines, order, order_line_by_id, product_by_id):
    """return_settlement (PRD §3.8). Returns dict with refund_subtotal_cents,
    restocking_fee_cents, settlement_cents.

    Handles REFUND, STORE_CREDIT, EXCHANGE variants.
    """
    reason = rma["reason"]
    resolution = rma["resolution"]

    refund_subtotal = 0
    restocking_fee_total = 0
    base_refund = 0
    exchange_target_total = 0

    fee_waived_global = (reason in ("DEFECTIVE", "WRONG_ITEM")) or (resolution != "REFUND")

    for rl in return_lines:
        ol = order_line_by_id[rl["order_line_id"]]
        return_qty = rl["return_qty"]
        ol_qty = ol["qty"]
        unit_snap = ol["unit_price_cents_snapshot"]

        returnable_subtotal = unit_snap * return_qty
        allocated_tax = round_half_up_int(ol["line_tax_cents"] * return_qty, ol_qty)

        # line promo: order.promo_flat_cents * (ol full subtotal) / order.subtotal_cents
        ol_full_subtotal = unit_snap * ol_qty
        if order["subtotal_cents"] > 0:
            line_promo = round_half_up_int(order["promo_flat_cents"] * ol_full_subtotal, order["subtotal_cents"])
        else:
            line_promo = 0
        qty_promo = round_half_up_int(line_promo * return_qty, ol_qty)

        if fee_waived_global:
            line_restock_fee = 0
        else:
            prod = product_by_id[ol["product_id"]]
            line_restock_fee = round_half_up_int(returnable_subtotal * prod["restocking_fee_bps"], 10000)

        refund_subtotal += returnable_subtotal
        restocking_fee_total += line_restock_fee
        base_refund += returnable_subtotal + allocated_tax - qty_promo

        # exchange target value
        if rl.get("exchange_product_id"):
            ex_prod = product_by_id.get(rl["exchange_product_id"])
            if ex_prod is not None:
                exchange_target_total += ex_prod["unit_price_cents"] * return_qty

    if resolution == "REFUND":
        settlement = max(0, base_refund - restocking_fee_total)
    elif resolution == "STORE_CREDIT":
        # fee waived (already excluded) + 5% bonus
        settlement = round_half_up_int(base_refund * (10000 + STORE_CREDIT_BONUS_BPS), 10000)
    else:  # EXCHANGE
        # sign-magnitude delta = exchange target value - refund_subtotal
        settlement = exchange_target_total - refund_subtotal

    return {
        "refund_subtotal_cents": refund_subtotal,
        "restocking_fee_cents": restocking_fee_total,
        "settlement_cents": settlement,
    }


def compute_return_risk(lifetime_purchased_cents, lifetime_refunded_cents):
    if lifetime_purchased_cents == 0:
        return 0.0
    return round_half_up_4(lifetime_refunded_cents, lifetime_purchased_cents)
