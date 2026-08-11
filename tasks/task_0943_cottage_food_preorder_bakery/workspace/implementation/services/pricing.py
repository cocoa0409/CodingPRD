"""Line pricing, per-line tax, delivery fee, tip, credit and the grand total.

All monetary results are integer cents.  Every fractional result is rounded
HALF UP.  Tax is rounded PER LINE and only then summed (PRD 2.5, pinned).
"""

from fractions import Fraction

import config
from db import DB
from errors import ApiError
from tsutil import cents, dec


def line_total(menu_item, quantity):
    """calculations.line_pricing -- non-monotone under PER_DOZEN_BAKERS."""
    basis = menu_item.get("pricing_basis")
    unit = menu_item.get("unit_price_cents") or 0
    dozen = menu_item.get("dozen_price_cents") or 0
    if basis == "PER_UNIT":
        return basis, quantity * unit
    full = quantity // config.BAKERS_DOZEN_UNITS
    rem = quantity % config.BAKERS_DOZEN_UNITS
    return basis, full * dozen + rem * unit


def line_tax(disposition, total_cents):
    """calculations.line_tax -- WHOLE_UNHEATED is exempt, everything else taxes."""
    taxable = disposition != "WHOLE_UNHEATED"
    if not taxable:
        return False, 0
    return True, cents(Fraction(total_cents * config.TAX_RATE_BPS, 10000))


def price_line(line, menu_item):
    """Price one line in place: basis, taxable, line_total_cents, line_tax_cents."""
    basis, total = line_total(menu_item, line.get("quantity") or 0)
    taxable, tax = line_tax(line.get("disposition"), total)
    line["pricing_basis_applied"] = basis
    line["taxable"] = taxable
    line["line_total_cents"] = total
    line["line_tax_cents"] = tax
    return line


def order_lines(order_id):
    return [l for l in DB.values("order_lines") if l.get("order_id") == order_id]


def order_subtotal(order_id):
    """calculations.order_subtotal -- excludes RELEASED and RECALL_VOID lines."""
    total = 0
    for line in order_lines(order_id):
        if line.get("line_status") in ("RELEASED", "RECALL_VOID"):
            continue
        total += line.get("line_total_cents") or 0
    return total


def order_tax_total(order_id):
    """calculations.order_tax_total -- PENDING lines only, per-line-then-sum."""
    total = 0
    for line in order_lines(order_id):
        if line.get("line_status") != "PENDING":
            continue
        total += line.get("line_tax_cents") or 0
    return total


def delivery_fee(handoff_mode, distance_km, reject_out_of_zone=True):
    """calculations.delivery_fee -- tier upper bounds are INCLUSIVE."""
    if handoff_mode in ("PICKUP_COUNTER", "PORCH_SELF_SERVE"):
        return 0
    d = Fraction(str(distance_km if distance_km is not None else 0))
    if d <= Fraction(str(config.DELIVERY_ZONE_TIER1_MAX_KM)):
        return config.DELIVERY_FEE_TIER1_CENTS
    if d <= Fraction(str(config.DELIVERY_ZONE_TIER2_MAX_KM)):
        return config.DELIVERY_FEE_TIER2_CENTS
    if d <= Fraction(str(config.DELIVERY_ZONE_TIER3_MAX_KM)):
        return config.DELIVERY_FEE_TIER3_CENTS
    if reject_out_of_zone:
        raise ApiError("ERR_OUT_OF_PERMITTED_ZONE",
                       "The delivery distance leaves the permitted zone.")
    return 0


def tip_amount(tip_mode, tip_pct, tip_fixed_cents, subtotal_cents):
    """calculations.tip_amount -- base is the SUBTOTAL alone."""
    if tip_mode == "PERCENT":
        return cents(dec(subtotal_cents) * dec(tip_pct if tip_pct is not None else 0))
    return int(tip_fixed_cents or 0)


def credit_eligible(order):
    return ((order.get("subtotal_cents") or 0)
            + (order.get("tax_total_cents") or 0)
            + (order.get("delivery_fee_cents") or 0))


def cycle_price(subscription, menu_item):
    """calculations.subscription_cycle_price -- window independent."""
    _basis, base = line_total(menu_item, subscription.get("units_per_cycle") or 0)
    if subscription.get("billing_mode") == "PREPAID":
        factor = dec(1) - dec(config.PREPAID_CYCLE_DISCOUNT_PCT)
        return cents(dec(base) * factor)
    return base


def quote(order):
    """GET /orders/{id}/quote -- the six pinned steps as already stored."""
    taxable_count = 0
    exempt_count = 0
    for line in order_lines(order["id"]):
        if line.get("line_status") in ("RELEASED", "RECALL_VOID"):
            continue
        if line.get("taxable"):
            taxable_count += 1
        else:
            exempt_count += 1
    return {
        "subtotal_cents": order.get("subtotal_cents") or 0,
        "tax_total_cents": order.get("tax_total_cents") or 0,
        "delivery_fee_cents": order.get("delivery_fee_cents") or 0,
        "tip_cents": order.get("tip_cents") or 0,
        "credit_applied_cents": order.get("credit_applied_cents") or 0,
        "grand_total_cents": order.get("grand_total_cents") or 0,
        "taxable_line_count": taxable_count,
        "exempt_line_count": exempt_count,
    }
