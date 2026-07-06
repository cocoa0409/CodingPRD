"""Delivery fee + order total pricing pipeline."""
from decimal import Decimal, ROUND_HALF_UP

BASE_FEE_CENTS = 500
ZONE_SURCHARGE_CENTS = {"ZONE_A": 0, "ZONE_B": 300, "ZONE_C": 700}
HEAVY_SURCHARGE_CENTS = 400
GIFT_SURCHARGE_CENTS = 200
MIN_FEE_CENTS = 800
MAX_FEE_CENTS = 3000
HEAVY_WAIVER_THRESHOLD_CENTS = 10000
TAX_RATE = Decimal("0.0875")


def delivery_fee(delivery_zone: str, heavy_present: bool, gift_flag: bool, subtotal_cents: int) -> int:
    base = BASE_FEE_CENTS
    zone_surcharge = ZONE_SURCHARGE_CENTS[delivery_zone]
    if heavy_present and delivery_zone != "ZONE_A" and subtotal_cents < HEAVY_WAIVER_THRESHOLD_CENTS:
        heavy_surcharge = HEAVY_SURCHARGE_CENTS
    else:
        heavy_surcharge = 0
    gift_surcharge = GIFT_SURCHARGE_CENTS if gift_flag else 0
    raw = base + zone_surcharge + heavy_surcharge + gift_surcharge
    return max(MIN_FEE_CENTS, min(raw, MAX_FEE_CENTS))


def order_total(subtotal_cents: int, applied_redemption_cents: int, delivery_fee_cents: int) -> int:
    """Pinned four-step evaluation. Only rounding step is the tax product (half-up)."""
    after_redemption = subtotal_cents - applied_redemption_cents
    tax_prod = Decimal(after_redemption) * TAX_RATE
    tax_cents = int(tax_prod.to_integral_value(rounding=ROUND_HALF_UP))
    return after_redemption + tax_cents + delivery_fee_cents
