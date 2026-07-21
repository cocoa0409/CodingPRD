"""Pure calculation helpers (pricing, fees, penalties). Uses Decimal / ROUND_HALF_UP."""
from decimal import Decimal, ROUND_HALF_UP

SMALL_MULT = Decimal("1.20")
STANDARD_MULT = Decimal("1.00")
LARGE_MULT = Decimal("0.90")
SERVICE_FEE_RATE = Decimal("0.0725")
INSURANCE_PREMIUM_RATE = Decimal("0.06")

MEAL_VOUCHER_CENTS = 2500
DEFAULT_DEPOSIT_CENTS = 20000
DOT_MAX_DRIVE_HOURS_PER_DAY = 10
TURNAROUND_BUFFER_DAYS = 1


def rhu(dec):
    """Round half up to whole integer."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def band_for_pax(pax):
    if pax < 6:
        return "SMALL"
    if pax < 12:
        return "STANDARD"
    return "LARGE"


def band_multiplier(band):
    return {"SMALL": SMALL_MULT, "STANDARD": STANDARD_MULT, "LARGE": LARGE_MULT}[band]


def per_person_price(base_price_cents, band):
    return rhu(Decimal(base_price_cents) * band_multiplier(band))


def service_fee(quoted_per_person_cents, pax_count):
    per_person_fee = rhu(Decimal(quoted_per_person_cents) * SERVICE_FEE_RATE)
    return per_person_fee * pax_count


def insurance_premium(base_subtotal_cents, insurance_opt_in):
    if not insurance_opt_in:
        return 0
    return rhu(Decimal(base_subtotal_cents) * INSURANCE_PREMIUM_RATE)


def penalty_pct(days_before):
    if days_before >= 60:
        return Decimal("0.10")
    if days_before >= 30:
        return Decimal("0.25")
    if days_before >= 15:
        return Decimal("0.50")
    return Decimal("1.00")
