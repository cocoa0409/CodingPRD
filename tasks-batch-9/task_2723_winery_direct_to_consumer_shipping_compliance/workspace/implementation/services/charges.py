"""The frozen money of an order: the twelve-step charge chain (PRD 3.5).

Every quantity is computed exactly once, at creation, and never revisited --
not by screening, not by an override, not by a return.
"""
from decimal import Decimal

from rounding import dec, rhu_liters, rhu_cents, floor_cents

SHIPPING_BASE_CENTS = 1500
SHIPPING_PER_LITER_CENTS = 220
LITER_TIER_1_MAX_L = Decimal("9.000")
LITER_TIER_2_MAX_L = Decimal("18.000")
CLUB_SHIPPING_DISCOUNT_BPS = 2500
FEE_WAIVER_THRESHOLD_CENTS = 20000
COMPLIANCE_HANDLING_FEE_CENTS = 900
SMALL_PRODUCER_MAX_GALLONS = 250000
SMALL_PRODUCER_CREDIT_BPS = 1500
LARGE_FORMAT_MIN_ML = 1500
BPS_DIVISOR = Decimal(10000)


def tier_multiplier(total_liters):
    """Step 4: selected from total_liters, applied BEFORE the club discount."""
    if total_liters <= LITER_TIER_1_MAX_L:
        return Decimal("1.00")
    if total_liters <= LITER_TIER_2_MAX_L:
        return Decimal("0.90")
    return Decimal("0.80")


def excise_for(total_liters, line_liters_over_large_format, rule, winery):
    """Base + large-format surcharge, then the small-producer credit, then the cap."""
    base = rhu_cents(dec(total_liters) * dec(rule["excise_rate_per_liter_cents"]))
    lf_liters = rhu_liters(line_liters_over_large_format)
    surcharge = rhu_cents(lf_liters * dec(rule["large_format_surcharge_cents_per_liter"]))
    gross = base + surcharge
    if winery["annual_production_gallons"] <= SMALL_PRODUCER_MAX_GALLONS:
        credit = rhu_cents(dec(gross) * Decimal(SMALL_PRODUCER_CREDIT_BPS) / BPS_DIVISOR)
    else:
        credit = 0
    credited = gross - credit
    cap = rule["excise_cap_cents_per_shipment"]
    # strictly last: the cap is applied after the credit, never before
    return credited if credited < cap else cap


def allocate_pool(lines, pool, total_liters):
    """Waterfall allocation of the taxable shipping/excise pool across lines.

    Each raw share is truncated downward; the remaining whole cents are handed
    out one at a time by line_liters DESC then line_index ASC.
    """
    for line in lines:
        if total_liters > 0:
            raw = dec(pool) * dec(line["line_liters"]) / dec(total_liters)
        else:
            raw = Decimal(0)
        line["allocated_shipping_cents"] = floor_cents(raw)
    remainder = pool - sum(l["allocated_shipping_cents"] for l in lines)
    if remainder > 0:
        order_of_hand_out = sorted(
            lines, key=lambda l: (-dec(l["line_liters"]), l["line_index"]))
        i = 0
        while remainder > 0 and order_of_hand_out:
            order_of_hand_out[i % len(order_of_hand_out)]["allocated_shipping_cents"] += 1
            remainder -= 1
            i += 1
    return lines


def compute(line_inputs, rule, winery, club):
    """Run the whole chain. Returns (order_money, line_rows)."""
    lines = []
    index = 0
    for raw in line_inputs:
        index += 1
        bottles = raw["bottles"]
        bottle_ml = raw["bottle_ml"]
        # step 1
        line_liters = rhu_liters(dec(bottles) * dec(bottle_ml) / Decimal(1000))
        lines.append({
            "line_index": index,
            "sku": raw["sku"],
            "bottle_ml": bottle_ml,
            "bottles": bottles,
            "unit_price_cents": raw["unit_price_cents"],
            "line_liters": line_liters,
            "line_subtotal_cents": bottles * raw["unit_price_cents"],
        })

    # step 2
    total_liters = rhu_liters(sum((l["line_liters"] for l in lines), Decimal(0)))
    subtotal_cents = sum(l["line_subtotal_cents"] for l in lines)

    # step 3
    shipping_gross_cents = rhu_cents(
        Decimal(SHIPPING_BASE_CENTS) + Decimal(SHIPPING_PER_LITER_CENTS) * total_liters)
    # steps 4 and 5 -- the tier multiplies the already-rounded gross
    shipping_tiered_cents = rhu_cents(dec(shipping_gross_cents) * tier_multiplier(total_liters))
    # step 6
    if club:
        shipping_discount_cents = rhu_cents(
            dec(shipping_tiered_cents) * Decimal(CLUB_SHIPPING_DISCOUNT_BPS) / BPS_DIVISOR)
    else:
        shipping_discount_cents = 0
    # step 7
    shipping_cents = shipping_tiered_cents - shipping_discount_cents

    # step 8
    large_format_liters = sum(
        (l["line_liters"] for l in lines if l["bottle_ml"] > LARGE_FORMAT_MIN_ML), Decimal(0))
    excise_tax_cents = excise_for(total_liters, large_format_liters, rule, winery)

    # step 9
    pool = 0
    if rule["tax_on_shipping"]:
        pool += shipping_cents
    if rule["excise_in_tax_base"]:
        pool += excise_tax_cents
    allocate_pool(lines, pool, total_liters)
    bps = dec(rule["sales_tax_rate_bps"])
    for line in lines:
        line["line_taxable_cents"] = line["line_subtotal_cents"] + line["allocated_shipping_cents"]
        line["line_sales_tax_cents"] = rhu_cents(
            dec(line["line_taxable_cents"]) * bps / BPS_DIVISOR)
    sales_tax_cents = sum(l["line_sales_tax_cents"] for l in lines)

    # steps 10 to 12
    pre_fee_total_cents = subtotal_cents + shipping_cents + excise_tax_cents + sales_tax_cents
    if pre_fee_total_cents >= FEE_WAIVER_THRESHOLD_CENTS:
        compliance_handling_fee_cents = 0
    else:
        compliance_handling_fee_cents = COMPLIANCE_HANDLING_FEE_CENTS
    total_cents = pre_fee_total_cents + compliance_handling_fee_cents

    money = {
        "total_liters": total_liters,
        "subtotal_cents": subtotal_cents,
        "shipping_gross_cents": shipping_gross_cents,
        "shipping_tiered_cents": shipping_tiered_cents,
        "shipping_discount_cents": shipping_discount_cents,
        "shipping_cents": shipping_cents,
        "excise_tax_cents": excise_tax_cents,
        "sales_tax_cents": sales_tax_cents,
        "pre_fee_total_cents": pre_fee_total_cents,
        "compliance_handling_fee_cents": compliance_handling_fee_cents,
        "total_cents": total_cents,
    }
    return money, lines
