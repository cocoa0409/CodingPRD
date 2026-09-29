"""Pricing calculations: quotes, invoices, volatility and inventory targets."""

import clock
import constants as C
import errors
from db import db
from util import D, add_days, money, rhu


# --------------------------------------------------------------------------
# Settlement price series helpers
# --------------------------------------------------------------------------
def _quote_rank_key(q):
    return (q["effective_date"], q["created_at"], q["_seq"])


def quotes_for_metal(metal):
    return [q for q in db.metal_price_quotes.values() if q["metal"] == metal]


def latest_quote_on_or_before(metal, day):
    """Rank effective_date DESC then created_at DESC and take the first."""
    candidates = [q for q in quotes_for_metal(metal) if q["effective_date"] <= day]
    if not candidates:
        return None
    candidates.sort(key=_quote_rank_key, reverse=True)
    return candidates[0]


def float_window_quotes(metal, ship_date):
    """The inclusive five-calendar-day window ending on ship_date."""
    start = add_days(ship_date, -(C.FLOAT_WINDOW_DAYS - 1)).isoformat()
    return [
        q for q in quotes_for_metal(metal)
        if start <= q["effective_date"] <= ship_date
    ]


# --------------------------------------------------------------------------
# Shared pass-through shape (PRD 3.5 step two / PRD 3.9)
# --------------------------------------------------------------------------
def unit_price(conversion_price, metal_price, product, customer):
    """conversion price plus the metal pass-through, 4 decimals half up."""
    if not customer["pass_through_enabled"]:
        pass_through = D("0")
    else:
        base = C.BASE_METAL_PRICE[product["conductor_metal"]]
        pass_through = product["conductor_lbs_per_kft"] * (D(metal_price) - base)
    return rhu(D(conversion_price) + pass_through, 4)


def surcharge_pct(extension):
    """Tier keyed on the rounded pre-surcharge extension only (PRD 3.5 step four)."""
    if extension < C.SURCHARGE_TIER_1_CEILING:
        return C.SURCHARGE_PCT_TIER_1
    if extension < C.SURCHARGE_TIER_2_CEILING:
        return C.SURCHARGE_PCT_TIER_2
    return C.SURCHARGE_PCT_TIER_3


def segment_extension(unit_price_kft, segments):
    """Round every cut segment to cents BEFORE summing (pinned order, PRD 2.5)."""
    total = D("0")
    for seg in segments:
        total += money(unit_price_kft * D(seg) / D("1000"))
    return money(total)


# --------------------------------------------------------------------------
# order_quoted_total (PRD 3.5)
# --------------------------------------------------------------------------
def order_quoted_total(order, product, customer):
    quote = latest_quote_on_or_before(product["conductor_metal"], order["order_date"])
    if quote is None:
        errors.fail(
            errors.ERR_NO_METAL_QUOTE,
            "No settlement price exists for %s at or before %s"
            % (product["conductor_metal"], order["order_date"]),
        )
    metal_price = D(quote["settlement_price_usd_per_lb"])

    unit = unit_price(order["conversion_price_usd_per_kft"], metal_price, product, customer)

    if order["cut_to_length_service"]:
        subtotal = segment_extension(unit, order["requested_cut_lengths_ft"])
        cut_fee = money(C.CUT_FEE_USD_PER_CUT * D(len(order["requested_cut_lengths_ft"])))
    else:
        subtotal = money(unit * D(order["ordered_kft"]))
        cut_fee = money("0")

    surcharge = money(subtotal * surcharge_pct(subtotal))
    total = money(subtotal + cut_fee + surcharge)

    order["quoted_metal_price_usd_per_lb"] = metal_price
    order["quoted_unit_price_usd_per_kft"] = unit
    order["quoted_subtotal_usd"] = subtotal
    order["quoted_cut_fee_usd"] = cut_fee
    order["quoted_surcharge_usd"] = surcharge
    order["quoted_total_usd"] = total
    return order


# --------------------------------------------------------------------------
# shipment_invoice_amount (PRD 3.9)
# --------------------------------------------------------------------------
def shipment_invoice_amount(shipment, order, product, customer):
    if order["price_basis"] == "ORDER_DATE_LOCK":
        metal_price = D(order["quoted_metal_price_usd_per_lb"])
        variant = "ORDER_DATE_LOCK"
    else:
        window = float_window_quotes(product["conductor_metal"], shipment["ship_date"])
        if len(window) < C.FLOAT_MIN_QUOTES:
            errors.fail(
                errors.ERR_INSUFFICIENT_PRICE_HISTORY,
                "Fewer than %d settlement prices in the float window ending %s"
                % (C.FLOAT_MIN_QUOTES, shipment["ship_date"]),
            )
        total = D("0")
        for q in window:
            total += D(q["settlement_price_usd_per_lb"])
        metal_price = rhu(total / D(len(window)), 4)
        variant = "SHIP_DATE_FLOAT"

    unit = unit_price(order["conversion_price_usd_per_kft"], metal_price, product, customer)

    if order["cut_to_length_service"]:
        segments = order["requested_cut_lengths_ft"][:int(shipment["cuts_count"])]
        extended = segment_extension(unit, segments)
        cut_fee = money(C.CUT_FEE_USD_PER_CUT * D(shipment["cuts_count"]))
    else:
        extended = money(unit * D(shipment["shipped_length_ft"]) / D("1000"))
        cut_fee = money("0")

    surcharge = money(extended * surcharge_pct(extended))
    invoice_amount = money(extended + cut_fee + surcharge)

    shipment["metal_price_used_usd_per_lb"] = metal_price
    shipment["price_variant_applied"] = variant
    shipment["unit_price_usd_per_kft"] = unit
    shipment["extended_amount_usd"] = extended
    shipment["cut_fee_usd"] = cut_fee
    shipment["volatility_surcharge_usd"] = surcharge
    shipment["invoice_amount_usd"] = invoice_amount
    shipment["invoice_date"] = clock.today_str()
    return shipment


# --------------------------------------------------------------------------
# metal_volatility_index + inventory_reposition_target (PRD 3.4)
# --------------------------------------------------------------------------
def metal_volatility_index(metal, as_of_date):
    window = [q for q in quotes_for_metal(metal) if q["effective_date"] <= as_of_date]
    window.sort(key=_quote_rank_key, reverse=True)
    window = window[:C.VOLATILITY_WINDOW_QUOTES]
    if len(window) < C.VOLATILITY_MIN_QUOTES:
        return rhu("0", 4)
    prices = [D(q["settlement_price_usd_per_lb"]) for q in window]
    total = D("0")
    for p in prices:
        total += p
    mean = total / D(len(prices))
    return rhu((max(prices) - min(prices)) / mean, 4)


def inventory_reposition_target(product):
    demand = D(product["demand_index"])
    if demand < C.DEMAND_LOW_CEILING:
        multiplier = C.DEMAND_MULT_LOW
    elif demand <= C.DEMAND_HIGH_CEILING:
        multiplier = C.DEMAND_MULT_MID
    else:
        multiplier = C.DEMAND_MULT_HIGH

    vi = D(product["volatility_index"])
    damper = D("1") - min(C.VOLATILITY_DAMPER_CAP, C.VOLATILITY_WEIGHT * vi)

    base = D(product["base_target_kft"])
    raw = base * multiplier * damper
    floor_kft = rhu(base * C.FLOOR_FACTOR, 1)
    ceiling_kft = rhu(base * C.CEILING_FACTOR, 1)
    clamped = min(max(raw, floor_kft), ceiling_kft)
    return rhu(clamped, 1)


# --------------------------------------------------------------------------
# reel_deposit_refund (PRD 3.9)
# --------------------------------------------------------------------------
def reel_deposit_refund(reel, condition, days_out):
    deposit = D(reel["deposit_usd"])
    if condition == "DAMAGED" or reel["reel_type"] == "NON_RETURNABLE":
        return money("0"), "NONE"
    if reel["reel_type"] == "WOOD_RETURNABLE":
        if days_out <= C.FLAT_FULL_DAYS:
            refund = money(deposit)
        elif days_out <= C.FLAT_HALF_DAYS:
            refund = money(deposit * D("0.50"))
        else:
            refund = money("0")
        return refund, "FLAT_STEP"
    # STEEL_RETURNABLE, GOOD condition
    pct = max(C.DECAY_FLOOR_PCT, D("1") - C.DECAY_PER_DAY * D(days_out))
    return money(deposit * pct), "DAILY_DECAY"
