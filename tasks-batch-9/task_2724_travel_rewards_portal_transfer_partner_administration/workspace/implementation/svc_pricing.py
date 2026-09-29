"""Offer pricing and parity (PRD 3.5) and redemption order pricing (PRD 3.6)."""

from decimal import Decimal

from core import ceil_int, dec, round_half_up

CARD_PRODUCTS = ("PREMIER", "CORE", "LEGACY_GOLD")

EARN_MULTIPLIER = {
    "PREMIER": Decimal("1.5"),
    "CORE": Decimal("1.0"),
    "LEGACY_GOLD": Decimal("2.0"),
}

CENTS_PER_POINT = {
    "PREMIER": Decimal("1.25"),
    "CORE": Decimal("1.0"),
    "LEGACY_GOLD": Decimal("1.5"),
}

BPS = Decimal(10000)


def portal_price_cents(net_rate_cents, contracted_markup_bps):
    """net rate grossed up by the contracted markup, rounded half up."""
    return round_half_up(dec(net_rate_cents) * (1 + dec(contracted_markup_bps) / BPS))


def parity_ceiling_cents(agency_public_price_cents, parity_tolerance_bps):
    return round_half_up(dec(agency_public_price_cents) * (1 + dec(parity_tolerance_bps) / BPS))


def parity_status(offer, agency):
    """Both limbs must pass: price ceiling and availability."""
    ceiling = parity_ceiling_cents(
        offer["agency_public_price_cents"], agency["parity_tolerance_bps"]
    )
    price_ok = offer["portal_price_cents"] <= ceiling
    availability_ok = offer["portal_seats"] <= offer["agency_public_seats"]
    return "IN_PARITY" if (price_ok and availability_ok) else "OUT_OF_PARITY"


def apply_offer_pricing(offer, agency):
    offer["portal_price_cents"] = portal_price_cents(
        offer["net_rate_cents"], agency["contracted_markup_bps"]
    )
    offer["cash_copay_cents"] = offer["tax_cents"]
    offer["parity_status"] = parity_status(offer, agency)
    return offer


# --------------------------------------------------------------------------
# redemption order pricing
# --------------------------------------------------------------------------
def cost_per_1k(cost_cents, points_debited):
    """cost * 1000 / points, rounded half up; 0 when there are no points."""
    if points_debited == 0:
        return 0
    return round_half_up(dec(cost_cents) * 1000 / dec(points_debited))


def price_portal_booking(order, offer, account):
    rate = CENTS_PER_POINT[account["card_product_code"]]
    order["cents_per_point_applied"] = float(rate)
    order["cash_copay_cents"] = offer["cash_copay_cents"]
    burn_cents = dec(offer["portal_price_cents"]) - dec(order["cash_copay_cents"])
    order["points_debited"] = ceil_int(burn_cents / rate)
    order["statement_credit_cents"] = 0
    provisional = offer["net_rate_cents"] - order["cash_copay_cents"]
    order["issuer_cost_provisional_cents"] = provisional
    order["cost_per_1k_provisional_cents"] = cost_per_1k(provisional, order["points_debited"])
    return order


def price_statement_credit(order, account, points_requested):
    rate = CENTS_PER_POINT[account["card_product_code"]]
    order["cents_per_point_applied"] = float(rate)
    order["points_debited"] = points_requested
    order["statement_credit_cents"] = round_half_up(dec(points_requested) * dec(1))
    order["cash_copay_cents"] = 0
    order["issuer_cost_provisional_cents"] = 0
    order["cost_per_1k_provisional_cents"] = 0
    return order


def blank_order(account_id, channel):
    """A freshly quoted order; both cost legs and every settlement field start null."""
    return {
        "account_id": account_id,
        "inventory_offer_id": None,
        "channel": channel,
        "traveler_name": None,
        "points_requested": None,
        "points_debited": 0,
        "cash_copay_cents": 0,
        "statement_credit_cents": 0,
        "cents_per_point_applied": 0,
        "issuer_cost_provisional_cents": 0,
        "issuer_cost_final_cents": None,
        "cost_per_1k_provisional_cents": 0,
        "cost_per_1k_final_cents": None,
        "invoice_amount_cents": None,
        "settlement_adjustment_cents": 0,
        "fulfillment_status": "QUOTED",
        "settlement_status": "UNSETTLED",
        "ticket_number": None,
        "pnr_locator": None,
        "confirmed_at": None,
        "ticketed_at": None,
        "settled_at": None,
        "closed_reason": None,
    }
