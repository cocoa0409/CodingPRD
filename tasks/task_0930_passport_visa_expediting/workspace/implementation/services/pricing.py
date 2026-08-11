"""Two-stream pricing: government total, the seven-step service waterfall and
the dual-variant tier change (PRD 3.5, calculations government_fee_total /
per_applicant_service_line / service_fee_total / tier_change_pricing)."""
from decimal import Decimal

from calendar_util import round_half_up
from constants import (
    MAX_DISCOUNT_PCT,
    MULTI_APPLICANT_DISCOUNT_PCT,
    MULTI_APPLICANT_MIN_COUNT,
    MULTI_APPLICANT_WAIVER_FLOOR_CENTS,
    ORDER_HANDLING_FEE_CENTS,
    TIER_SURCHARGE,
    TIER_UPGRADE_ADMIN_FEE_CENTS,
)
from services import lookup, money

ZERO = Decimal("0.00")


def recompute_applicant_count(order):
    order["applicant_count"] = len(lookup.counted_applicants(order))
    return order["applicant_count"]


def government_fee_total(order, catalog):
    n = order["applicant_count"]
    if catalog["government_fee_basis"] == "PER_ORDER":
        return catalog["government_fee_cents"]
    return catalog["government_fee_cents"] * n


def per_applicant_service_line(order, catalog, discount_pct, count):
    """ROUND PER LINE, then sum -- summing first is explicitly not the pinned order."""
    tier_pct = TIER_SURCHARGE[order["service_level"]]
    base = Decimal(catalog["base_service_fee_cents"])
    line_raw = base * (Decimal("1") + tier_pct)
    line_net = line_raw * (Decimal("1") - discount_pct)
    line_cents = round_half_up(line_net)
    return line_cents * count


def service_fee_total(order, catalog, promo_discount_pct):
    n = order["applicant_count"]
    # Step 1
    auto_pct = MULTI_APPLICANT_DISCOUNT_PCT if n >= MULTI_APPLICANT_MIN_COUNT else ZERO
    # Step 2
    discount_pct = auto_pct + (promo_discount_pct or ZERO)
    if discount_pct > MAX_DISCOUNT_PCT:
        discount_pct = MAX_DISCOUNT_PCT
    # Step 3
    subtotal = per_applicant_service_line(order, catalog, discount_pct, n)
    # Step 4
    waived = (n >= MULTI_APPLICANT_MIN_COUNT) and (subtotal >= MULTI_APPLICANT_WAIVER_FLOOR_CENTS)
    # Step 5
    handling = 0 if waived else ORDER_HANDLING_FEE_CENTS
    # Step 6
    return subtotal + handling, discount_pct, waived


def run_full_quote(order, promo_discount_pct):
    """Both streams from scratch; writes every quoted money field."""
    catalog = lookup.catalog_of(order)
    recompute_applicant_count(order)
    order["government_fee_quoted_cents"] = government_fee_total(order, catalog)
    service_total, discount_pct, waived = service_fee_total(order, catalog, promo_discount_pct)
    order["service_fee_quoted_cents"] = service_total
    order["discount_pct_applied"] = discount_pct
    order["handling_fee_waived"] = waived
    order["total_quoted_cents"] = (
        order["government_fee_quoted_cents"] + order["service_fee_quoted_cents"]
    )
    return order


def apply_in_flight_delta(order):
    """Only the difference is priced; discount and waiver are FROZEN."""
    catalog = lookup.catalog_of(order)
    n = order["applicant_count"]
    discount_pct = order["discount_pct_applied"]
    if not isinstance(discount_pct, Decimal):
        discount_pct = Decimal(str(discount_pct))
    new_subtotal = per_applicant_service_line(order, catalog, discount_pct, n)
    embedded_handling = 0 if order["handling_fee_waived"] else ORDER_HANDLING_FEE_CENTS
    old_subtotal = order["service_fee_quoted_cents"] - embedded_handling
    delta = new_subtotal - old_subtotal + TIER_UPGRADE_ADMIN_FEE_CENTS
    order["service_fee_quoted_cents"] += delta
    order["total_quoted_cents"] = (
        order["government_fee_quoted_cents"] + order["service_fee_quoted_cents"]
    )
    return delta


def redrive_money_rollups(order):
    money.recompute_collected(order)
    money.derive_payment_status(order)
