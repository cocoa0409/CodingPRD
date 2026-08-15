"""Monetary helpers (PRD section 2.7). Integer cents, round-half-up, pinned
rounding points. Never float arithmetic for money."""

from decimal import Decimal, ROUND_HALF_UP

SUBCONTRACTOR_MARKUP = Decimal("1.15")
NO_MARKUP = Decimal("1.0")
OWNER_PARTS_FEE_PCT = Decimal("0.10")
DEPOSIT_PCT = Decimal("0.25")
WINTER_MULTIPLIER = Decimal("0.85")
NO_WINTER = Decimal("1.0")

TIER1_CENTS_PER_FT = 50
TIER1_MAX_DAY = 7
TIER2_CENTS_PER_FT = 65
TIER2_MAX_DAY = 30
TIER3_CENTS_PER_FT = 85
MONTHLY_BLOCK_CENTS_PER_FT = 1400
MONTHLY_BLOCK_DAYS = 30

VIOLATION_PPM = 100.0
ADVISORY_PPM = 50.0
LIFT_BUFFER_MINUTES = 30
LIFT_CAPACITY_TONS = 60
INSURANCE_MIN_LIABILITY_CENTS = 100000000


def dec(v):
    return Decimal(str(v))


def rhu(d):
    """Round half-up to 0 decimal places, returning an int of cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
