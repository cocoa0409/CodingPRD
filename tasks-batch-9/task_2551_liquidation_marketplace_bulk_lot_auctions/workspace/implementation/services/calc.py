"""Pure calculations (PRD 3.x). Integer cents, Decimal, half-up rounding."""

import math
from decimal import Decimal

from util import bps_of, money, round_half_up

# --- buyer premium: flat tiers on the hammer price (PRD 3.6) ------------------
PREMIUM_TIER_LOW_MAX = 1000000
PREMIUM_TIER_MID_MAX = 2500000
PREMIUM_BPS_LOW = 1400
PREMIUM_BPS_MID = 1200
PREMIUM_BPS_HIGH = 1000

# --- freight ------------------------------------------------------------------
UNITS_PER_PALLET = 200
FREIGHT_CENTS_PER_PALLET = 8500

# --- settlement ---------------------------------------------------------------
PAYMENT_TERM_DAYS = 3
PICKUP_TERM_DAYS = 10
CLAIM_WINDOW_DAYS = 5
LATE_FEE_BPS = 150

# --- negotiation --------------------------------------------------------------
OFFER_TTL_HOURS = 48
MAX_NEGOTIATION_ROUNDS = 4

# --- auction ------------------------------------------------------------------
ANTI_SNIPE_TRIGGER_SECONDS = 120
ANTI_SNIPE_EXTENSION_SECONDS = 300
MAX_EXTENSIONS = 3
DEFAULT_BID_INCREMENT_CENTS = 100000

# --- commission ---------------------------------------------------------------
TIER_STANDARD_BPS = 2000
TIER_PREFERRED_BPS = 1500
TIER_PROBATION_BPS = 2500
PREFERRED_GROSS_RECOVERY_THRESHOLD = Decimal("0.2500")
PROBATION_ACCURACY_THRESHOLD = Decimal("0.850")

# --- manifest accuracy tolerance by condition grade ---------------------------
ACCURACY_TOLERANCE = {
    "NEW_OVERSTOCK": Decimal("0.01"),
    "CUSTOMER_RETURNS": Decimal("0.03"),
    "SALVAGE": Decimal("0.08"),
}


def premium_bps(hammer_cents):
    """Flat (not marginal) tier selection on the hammer price."""
    if hammer_cents <= PREMIUM_TIER_LOW_MAX:
        return PREMIUM_BPS_LOW
    if hammer_cents <= PREMIUM_TIER_MID_MAX:
        return PREMIUM_BPS_MID
    return PREMIUM_BPS_HIGH


def buyer_premium_cents(hammer_cents, bps=None):
    if bps is None:
        bps = premium_bps(hammer_cents)
    return bps_of(hammer_cents, bps)


def pallet_count(declared_unit_count):
    return int(math.ceil(Decimal(int(declared_unit_count)) / Decimal(UNITS_PER_PALLET)))


def freight_cents(pallets):
    return int(pallets) * FREIGHT_CENTS_PER_PALLET


def late_fee_cents(pre_fee_total_cents):
    return bps_of(pre_fee_total_cents, LATE_FEE_BPS)


def line_extended_cents(line):
    return int(line["unit_count"]) * int(line["unit_retail_cents"])


def line_share_cents(hammer_cents, line, declared_retail_value_cents):
    """Proportional share of the hammer attributable to one manifest line."""
    if not declared_retail_value_cents:
        return 0
    extended = line_extended_cents(line)
    return money(
        Decimal(int(hammer_cents)) * Decimal(extended)
        / Decimal(int(declared_retail_value_cents))
    )


def claim_refund_cents(order, lot, line, verified_units):
    """PRD 3.8 refund arithmetic: share, per-unit, base, premium."""
    if verified_units <= 0:
        return 0
    share = line_share_cents(
        order["hammer_price_cents"], line, lot["declared_retail_value_cents"]
    )
    per_unit = money(Decimal(share) / Decimal(int(line["unit_count"])))
    base = per_unit * int(verified_units)
    premium = bps_of(base, order["buyer_premium_bps"])
    return base + premium


def accuracy_score(lot, total_verified_units):
    """1 - excess/declared, three digits, clamped to [0.000, 1.000]."""
    declared = int(lot["declared_unit_count"])
    if declared <= 0:
        return 1.0
    tolerance = ACCURACY_TOLERANCE.get(lot["condition_grade"], Decimal("0"))
    allowed = int((Decimal(declared) * tolerance).to_integral_value(rounding="ROUND_FLOOR"))
    excess = max(0, int(total_verified_units) - allowed)
    raw = Decimal(1) - (Decimal(excess) / Decimal(declared))
    rounded = round_half_up(raw, 3)
    if rounded < Decimal("0.000"):
        rounded = Decimal("0.000")
    if rounded > Decimal("1.000"):
        rounded = Decimal("1.000")
    return float(rounded)


def average_accuracy(scores):
    """Mean of already-rounded lot scores, rounded half up to three digits."""
    if not scores:
        return 1.0
    total = sum((Decimal(str(score)) for score in scores), Decimal(0))
    return float(round_half_up(total / Decimal(len(scores)), 3))
