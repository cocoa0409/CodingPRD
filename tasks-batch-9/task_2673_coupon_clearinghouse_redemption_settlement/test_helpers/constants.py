"""Domain constants, literals and pure helpers for the clearinghouse test suite.

Every value here is taken from the PRD: the logical clock's startup instant,
the rounding disciplines, the barcode minting rules, the fee bands and the
threshold ladders. Nothing is invented and nothing is read from the server.
"""

from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

# "It keeps a logical clock whose value at startup is exactly 2026-08-01T00:00:00Z"
CLOCK_START_UTC = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

# "the dispute service-level allowance of 30 days"
DISPUTE_SLA_DAYS = 30

# ---------------------------------------------------------------------------
# Money and rounding (PRD 2.6)
# ---------------------------------------------------------------------------

RATE_DECIMALS = 2          # component rates, fraud scores, count_variance_pct
HOLDBACK_DECIMALS = 4      # holdback_pct
UNIT_RATE_DECIMALS = 4     # extrapolated unit-accept rate

# ---------------------------------------------------------------------------
# Intake (PRD 3.3)
# ---------------------------------------------------------------------------

COUNT_VARIANCE_TOLERANCE_PCT = Decimal("2.00")
SAMPLE_THRESHOLD_QTY = 40
SAMPLE_RATE_NUMERATOR = 10
SAMPLE_RATE_DENOMINATOR = 100

# ---------------------------------------------------------------------------
# Handling fees (PRD 3.5)
# ---------------------------------------------------------------------------

TIER_MULTIPLIER = {
    "PREFERRED": Decimal("1.15"),
    "STANDARD": Decimal("1.00"),
    "PROBATION": Decimal("0.80"),
}

# 8 cents per unit for up to 99 units, 7 cents for 100 through 499,
# 6 cents at 500 units and above.
TIERED_FEE_BANDS = ((99, 8), (499, 7), (None, 6))

# ---------------------------------------------------------------------------
# Statement waterfall (PRD 3.8)
# ---------------------------------------------------------------------------

HOLDBACK_BAND_1_CENTS = 100000
HOLDBACK_BAND_2_CENTS = 1000000
HOLDBACK_BAND_0_PCT = Decimal("0.00")
HOLDBACK_BAND_1_PCT = Decimal("0.02")
HOLDBACK_BAND_2_PCT = Decimal("0.05")
HOLDBACK_RISK_ADD_PCT = Decimal("0.03")
HOLDBACK_CAP_PCT = Decimal("0.06")
MISREDEMPTION_RISK_THRESHOLD_PCT = Decimal("5.00")

CLEARING_FEE_PCT = Decimal("0.015")

NET_TERM_DAYS = {"NET_15": 15, "NET_30": 30, "NET_45": 45}

BILLING_PERIOD_BUFFER_DAYS = 1

# ---------------------------------------------------------------------------
# Fraud scoring (PRD 3.6)
# ---------------------------------------------------------------------------

DUPLICATE_WEIGHT = Decimal("1.40")
MISREDEMPTION_WEIGHT = Decimal("1.00")
COUNTERFEIT_WEIGHT = Decimal("2.00")
FRAUD_SCORE_CLAMP = Decimal("100.00")
FRAUD_WINDOW_DAYS = 90
FRAUD_DECAY_HALFLIFE_DAYS = 180
FRAUD_WATCHLIST_THRESHOLD = Decimal("70.00")
FRAUD_SUSPEND_THRESHOLD = Decimal("90.00")

# ---------------------------------------------------------------------------
# Digital clearing (PRD 3.9)
# ---------------------------------------------------------------------------

CLIP_CONCURRENCY_LIMIT = 2

# ---------------------------------------------------------------------------
# Barcode minting (PRD 3.2)
# ---------------------------------------------------------------------------

DATABAR_FAMILY_CODE = "811"
UPC_COUPON_NUMBER_SYSTEM = "5"
EXT5_UNITS_MULTIPLIER = 1000

# ---------------------------------------------------------------------------
# Disputes (PRD 3.7)
# ---------------------------------------------------------------------------

MAX_INFO_ROUNDS = 2
DISPUTE_REASON_CODES = (
    "WRONG_EXPIRY_CALL",
    "IMAGE_QUALITY",
    "POS_DATA_LATE",
    "DUPLICATE_MISMATCH",
)

# ---------------------------------------------------------------------------
# Canonical fixture literals reused across the suite
# ---------------------------------------------------------------------------

PREFIX_A = "038000"
PREFIX_B = "041000"
PREFIX_C = "072250"

CANONICAL_FACE_VALUE_CENTS = 50
CANONICAL_HANDLING_FEE_CENTS = 7
CANONICAL_EXPIRATION_DATE = "2026-12-31"
CANONICAL_GRACE_DAYS = 30
CANONICAL_INSTRUCTIONS = "Mail to the clearinghouse with the register tape attached."

# A UUID-shaped identifier that never resolves to a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "11111111-1111-4111-8111-111111111111"
UNKNOWN_UUID_LOT = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Pure helpers mirroring the PRD's arithmetic
# ---------------------------------------------------------------------------

def round_half_up(value, places: int = 0):
    """Round half up to `places` decimals, as PRD 2.6 mandates everywhere."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else result


def databar_payload(prefix: str, face_value_cents: int, units: int,
                    expiration_date: str, grace_days: int) -> str:
    """Mint a GS1_DATABAR payload exactly as PRD 3.2 specifies."""
    year, month, day = expiration_date.split("-")
    yymmdd = f"{year[2:]}{month}{day}"
    return (
        DATABAR_FAMILY_CODE
        + prefix
        + f"{face_value_cents:05d}"
        + f"{units:02d}"
        + yymmdd
        + f"{grace_days:03d}"
    )


def upc_ext5_payload(prefix: str, face_value_cents: int, units: int,
                     grace_days: int) -> str:
    """Mint a UPC_A_WITH_EXT5 payload exactly as PRD 3.2 specifies."""
    ext5 = units * EXT5_UNITS_MULTIPLIER + grace_days
    return (
        UPC_COUPON_NUMBER_SYSTEM
        + prefix
        + f"{face_value_cents:05d}"
        + f"{ext5:05d}"
    )


# The canonical offer used by most fixtures: face 50, one qualifying unit,
# expiring 2026-12-31 with 30 grace days, on the databar family.
CANONICAL_DATABAR_PAYLOAD = databar_payload(
    PREFIX_A, CANONICAL_FACE_VALUE_CENTS, 1, CANONICAL_EXPIRATION_DATE,
    CANONICAL_GRACE_DAYS,
)
# A payload that differs from the canonical one only in its face value, so a
# coupon scanned with it is counterfeit by byte comparison.
COUNTERFEIT_DATABAR_PAYLOAD = databar_payload(
    PREFIX_A, 40, 1, CANONICAL_EXPIRATION_DATE, CANONICAL_GRACE_DAYS,
)


def add_days(date_str: str, days: int) -> str:
    """Calendar-date arithmetic on an ISO date string."""
    base = _dt.date.fromisoformat(date_str)
    return (base + _dt.timedelta(days=days)).isoformat()


def clock_instant(date_str: str, time_part: str = "00:00:00") -> str:
    """Build a clock instant from a calendar date."""
    return f"{date_str}T{time_part}Z"


def iso_millis(date_str: str, time_part: str = "00:00:00") -> str:
    """The three-fractional-digit instant the server stores for that date."""
    return f"{date_str}T{time_part}.000Z"
