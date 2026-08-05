"""Domain thresholds and monetary constants from the PRD calculations (§2.6, §3.4, §3.6)."""

# Quarter-hour grid (§2.6)
QUARTER_HOUR = 0.25

# Conversion-fee sliding scale and clamp band (§3.6)
BASE_CONVERSION_RATE_CENTS = 1500
INDIGENCY_MULTIPLIER = {"NONE": 1.0, "PARTIAL": 0.5, "FULL": 0.25}
MIN_FEE_CENTS = 2500
MAX_FEE_CENTS = 200000

# Participant rest buffer (§3.4)
REST_BUFFER_MINUTES = 60

# Shared bootstrap literals used across setup helpers.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
DEFAULT_POLICY_EFFECTIVE = "2026-01-01T00:00:00Z"
DEFAULT_POLICY_EXPIRY = "2027-01-01T00:00:00Z"
DEFAULT_DEADLINE = "2026-12-31T00:00:00Z"


def conversion_fee_cents(hours: float, tier: str) -> int:
    """Reference sliding-scale-then-clamp fee, matching PRD §3.6.

    rate = BASE * multiplier[tier]; raw = round_half_up(hours * rate);
    fee = min(MAX, max(MIN, raw)).
    """
    import decimal
    rate = BASE_CONVERSION_RATE_CENTS * INDIGENCY_MULTIPLIER[tier]
    raw = decimal.Decimal(str(hours * rate)).quantize(
        decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP)
    raw = int(raw)
    return min(MAX_FEE_CENTS, max(MIN_FEE_CENTS, raw))
