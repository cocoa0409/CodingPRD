"""Pricing and financial calculations: press_quote_price, final_invoice_total,
overrun_billing_units, cancellation_fee, credit_availability, storage_fee."""

import math
from decimal import Decimal, ROUND_HALF_UP

from .constants import (
    TIER1_LIMIT, TIER1_RATE, TIER2_LIMIT, TIER2_RATE, TIER3_LIMIT, TIER3_RATE,
    TIER4_RATE, VARIANT_SURCHARGE, MIN_VARIANT_SURCHARGE, WEIGHT_SURCHARGE,
    LACQUER_PER_SIDE, STAMPER_FEE, STAMPER_LIFE, SETUP_ORDER,
    SETUP_PER_NONBLACK_VARIANT, TIER_PCT, OVERRUN_PCT, UNDERRUN_PCT,
    TP_REVISION_FEE, REPRESS_FLAT, CANCEL_PCT, UNITS_PER_PALLET,
    DAILY_PALLET_RATE, MONTHLY_PALLET_RATE, MIN_MONTHLY_STORAGE,
)


def round_half_up(value):
    """Round a Decimal (or int) half-up to whole units, returning int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal half-up to two decimal places, returning Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def marginal_tier_price(units):
    """Marginal tier sum over `units`:
    first 299 @ 320, next 700 (300..999) @ 275, next 4000 (1000..4999) @ 240,
    remainder (5000+) @ 210."""
    remaining = units
    total = 0
    t1 = min(remaining, TIER1_LIMIT)
    total += t1 * TIER1_RATE
    remaining -= t1
    if remaining <= 0:
        return total
    t2 = min(remaining, TIER2_LIMIT - TIER1_LIMIT)
    total += t2 * TIER2_RATE
    remaining -= t2
    if remaining <= 0:
        return total
    t3 = min(remaining, TIER3_LIMIT - TIER2_LIMIT)
    total += t3 * TIER3_RATE
    remaining -= t3
    if remaining <= 0:
        return total
    total += remaining * TIER4_RATE
    return total


def dominant_variant(variants):
    """Largest-quantity variant; ties broken by first in array."""
    best = None
    for v in variants:
        if best is None or v["quantity"] > best["quantity"]:
            best = v
    return best


def compute_quote(order, release, customer):
    """press_quote_price: returns dict of the seven quote components plus
    discount_pct_snapshot."""
    q = order["quantity_ordered"]
    variants = order["variants"]
    weight = release["weight_gram"]
    sides = order["sides"]

    # Tier percentage snapshot: 0 if customer SUSPENDED at quote time
    if customer["status"] == "SUSPENDED":
        pct = Decimal("0")
    else:
        pct = TIER_PCT[customer["discount_tier"]]

    # 1. pressing
    pressing = marginal_tier_price(q)

    # 2. surcharge: per-variant max(qty*rate, floor) [BLACK exempt from floor]
    #    + Q * weight surcharge
    surcharge = 0
    for v in variants:
        cfg = v["color_config"]
        qty = v["quantity"]
        if cfg == "BLACK":
            surcharge += qty * 0
        else:
            line = qty * VARIANT_SURCHARGE[cfg]
            surcharge += max(line, MIN_VARIANT_SURCHARGE)
    surcharge += q * WEIGHT_SURCHARGE[weight]

    # 3. tooling
    stampers = math.ceil(q / STAMPER_LIFE)
    tooling = sides * LACQUER_PER_SIDE + stampers * sides * STAMPER_FEE

    # 4. setup
    nonblack = sum(1 for v in variants if v["color_config"] != "BLACK")
    setup = SETUP_ORDER + SETUP_PER_NONBLACK_VARIANT * nonblack

    subtotal = pressing + surcharge + tooling + setup
    discount = round_half_up(Decimal(subtotal) * pct)
    total = subtotal - discount

    return {
        "quote_pressing_cents": pressing,
        "quote_surcharge_cents": surcharge,
        "quote_tooling_cents": tooling,
        "quote_setup_cents": setup,
        "quote_subtotal_cents": subtotal,
        "quote_discount_cents": discount,
        "quote_total_cents": total,
        "discount_pct_snapshot": float(pct),
    }


def billed_units(order, customer):
    """overrun_billing_units: billed unit count B from the overrun policy."""
    policy = order.get("overrun_policy") or customer["overrun_policy"]
    a = order["accepted_units"]
    q = order["quantity_ordered"]
    if policy == "EXACT_ONLY":
        return min(a, q)
    if policy == "ACCEPT_AND_BILL_10":
        cap = math.floor(Decimal(q) * (Decimal("1") + OVERRUN_PCT))
        return min(a, cap)
    # ACCEPT_ALL_AND_BILL
    return a


def compute_final_invoice(order, release, customer):
    """final_invoice_total: build the seven invoice lines with pinned per-line
    rounding. Returns (lines, gross_cents, discount_cents, net_cents)."""
    pct = Decimal(str(order["discount_pct_snapshot"]))
    a = order["accepted_units"]
    q = order["quantity_ordered"]
    b = billed_units(order, customer)

    # Line 1: pressing
    pressing_gross = marginal_tier_price(b)

    # Line 2: surcharge — dominant variant surcharge + weight surcharge, per unit
    dom = dominant_variant(order["variants"])
    s_dom = VARIANT_SURCHARGE[dom["color_config"]]
    w = WEIGHT_SURCHARGE[release["weight_gram"]]
    surcharge_gross = b * (s_dom + w)

    # Line 3: tooling
    tooling_gross = order["quote_tooling_cents"]
    if order["repress_fault"] == "CUSTOMER":
        tooling_gross += order["repress_round"] * order["sides"] * STAMPER_FEE

    # Line 4: setup
    setup_gross = order["quote_setup_cents"]

    # Line 5: tp revision
    tp_revision_gross = max(0, order["tp_round"] - 1) * TP_REVISION_FEE

    # Line 6: underrun credit (negative gross)
    underrun_gross = 0
    floor90 = math.floor(Decimal(q) * (Decimal("1") - UNDERRUN_PCT))
    if a < floor90 and b > 0:
        shortfall = floor90 - a
        underrun_gross = -round_half_up(
            Decimal(shortfall) * Decimal(pressing_gross) / Decimal(b)
        )

    # Line 7: repress adjustment
    repress_gross = 0
    if order["repress_fault"] == "PLANT":
        repress_gross = -(order["repress_round"] * REPRESS_FLAT)
    elif order["repress_fault"] == "CUSTOMER":
        repress_gross = order["repress_round"] * REPRESS_FLAT

    grosses = [
        ("pressing", pressing_gross),
        ("surcharge", surcharge_gross),
        ("tooling", tooling_gross),
        ("setup", setup_gross),
        ("tp_revision", tp_revision_gross),
        ("underrun", underrun_gross),
        ("repress", repress_gross),
    ]

    lines = []
    gross_cents = 0
    discount_cents = 0
    net_cents = 0
    for label, gross in grosses:
        # Per-line pinned rounding. For negative gross the half-up rounding is
        # applied to the signed value (ROUND_HALF_UP rounds away from zero on
        # the .5 boundary, symmetric for negatives).
        line_discount = round_half_up(Decimal(gross) * pct)
        line_net = gross - line_discount
        lines.append({
            "label": label,
            "gross_cents": gross,
            "discount_cents": line_discount,
            "net_cents": line_net,
        })
        gross_cents += gross
        discount_cents += line_discount
        net_cents += line_net

    return lines, gross_cents, discount_cents, net_cents


def cancellation_fee(order):
    """cancellation_fee: tiered fee from state at cancel time."""
    pct = CANCEL_PCT[order["production_status"]]
    return round_half_up(Decimal(order["quote_total_cents"]) * pct)


def credit_outstanding(customer_id, invoices):
    """credit_availability: outstanding balance across ISSUED/PARTIALLY_PAID
    invoices of the customer."""
    total = 0
    for inv in invoices.values():
        if inv["customer_id"] == customer_id and inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            total += inv["net_cents"] - inv["paid_cents"] - inv["credited_cents"]
    return total


def storage_fees(lot, release):
    """storage_fee: dual-variant computation over the trailing 30 days ending
    at the logical clock.

    We track per-day on-hand history in lot['_daily_on_hand'] (date-string ->
    on_hand at end of that day). Days without a recorded change take the most
    recent prior value; days before the lot existed count as 0.
    """
    import db
    today = db.today_logical()
    upp = UNITS_PER_PALLET[release["format"]]
    history = lot.get("_daily_on_hand", {})

    pallets_by_day = []
    for i in range(29, -1, -1):
        from datetime import timedelta
        day = today - timedelta(days=i)
        key = day.isoformat()
        if key in history:
            on_hand = history[key]
        else:
            # most recent recorded value on or before this day
            prior_days = [d for d in history if d <= key]
            if prior_days:
                on_hand = history[max(prior_days)]
            else:
                on_hand = 0
        pallets_by_day.append(math.ceil(on_hand / upp) if on_hand > 0 else 0)

    # daily accrual variant
    daily_accrual = sum(p * DAILY_PALLET_RATE for p in pallets_by_day)

    # monthly statement variant: average pallets over the days in the window
    days_in_month = len(pallets_by_day)
    avg_pallets = round_half_up_2dp(
        Decimal(sum(pallets_by_day)) / Decimal(days_in_month)
    )
    monthly = max(
        round_half_up(avg_pallets * MONTHLY_PALLET_RATE),
        MIN_MONTHLY_STORAGE,
    )
    return daily_accrual, monthly
