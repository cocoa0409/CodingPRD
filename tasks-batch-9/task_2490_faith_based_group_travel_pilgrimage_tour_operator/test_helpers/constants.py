"""Literal values the PRD pins, plus the reusable product catalogues.

Every money figure is in cents and every rate in basis points, divided by
10,000 and rounded half up (PRD §2.6).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Invoice arithmetic (PRD §3.5)
# ---------------------------------------------------------------------------

BOOKING_FEE_BP = 350
GRANT_TIER_HIGH_THRESHOLD_CENTS = 500_000
GRANT_TIER_HIGH_BP = 500
GRANT_TIER_MID_THRESHOLD_CENTS = 300_000
GRANT_TIER_MID_BP = 300

# ---------------------------------------------------------------------------
# Protection premium (PRD §3.8)
# ---------------------------------------------------------------------------

AGE_BAND_D_MIN_AGE = 75
AGE_BAND_D_BP = 1280
AGE_BAND_C_MIN_AGE = 65
AGE_BAND_C_BP = 910
AGE_BAND_B_MIN_AGE = 40
AGE_BAND_B_BP = 620
AGE_BAND_A_BP = 400

MEDICAL_UPLIFT_THRESHOLD_CENTS = 5_000_000
MEDICAL_UPLIFT_BP = 1500
WAIVER_SURCHARGE_BP = 2200
WAIVER_SURCHARGE_CAP_CENTS = 45_000

WAIVER_STABLE_PERIOD_MIN_DAYS = 60
WAIVER_WINDOW_DAYS = 21

SENIOR_PROTECTION_MIN_AGE = 70

# ---------------------------------------------------------------------------
# Air deviation (PRD §3.6)
# ---------------------------------------------------------------------------

ORIGIN_CHANGE_FEE_CENTS = 12_500
DATE_DEVIATION_FEE_CENTS = 9_000
CLASS_UPGRADE_BP = 4500
LATE_DEVIATION_DAYS = 30
LATE_DEVIATION_BP = 15_000
EARLY_DEVIATION_BP = 10_000

# ---------------------------------------------------------------------------
# Rooming and dietary (PRD §3.5)
# ---------------------------------------------------------------------------

ROOM_CAPACITY = {"SINGLE": 1, "DOUBLE": 2, "TWIN": 2}
DIETARY_LEAD_TIME_DAYS = 21
LEAD_TIME_DIETARY_CODES = ("KOSHER", "HALAL")

# ---------------------------------------------------------------------------
# Payment defaults (PRD §3.7)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD_PAST_DUE_COUNT = 2
INSTALLMENT_COUNTS = {"SINGLE_BALANCE": 1, "MONTHLY_3": 3, "MONTHLY_6": 6}

# ---------------------------------------------------------------------------
# Risk posture (PRD §3.9)
# ---------------------------------------------------------------------------

ADVISORY_SEVERITY_RANK = {
    "NORMAL": 0,
    "EXERCISE_CAUTION": 1,
    "RECONSIDER": 2,
    "DO_NOT_TRAVEL": 3,
}
POSTURE_FOR_LEVEL = {
    "NORMAL": "OPEN",
    "EXERCISE_CAUTION": "WATCH",
    "RECONSIDER": "RESTRICTED",
    "DO_NOT_TRAVEL": "SUSPENDED",
}
RISK_SUSPENSION_REASON = "RISK_SUSPENSION"

# ---------------------------------------------------------------------------
# Product catalogue: Holy Land Small Group (the workhorse programme)
# ---------------------------------------------------------------------------

HOLY_LAND_TIERS = [
    {
        "tier_code": "T1",
        "min_pax": 1,
        "max_pax": 9,
        "per_pax_price_cents": 587_000,
        "single_supplement_cents": 98_000,
        "deposit_cents": 50_000,
    },
    {
        "tier_code": "T2",
        "min_pax": 10,
        "max_pax": 19,
        "per_pax_price_cents": 529_000,
        "single_supplement_cents": 92_000,
        "deposit_cents": 50_000,
    },
    {
        "tier_code": "T3",
        "min_pax": 20,
        "max_pax": 40,
        "per_pax_price_cents": 488_000,
        "single_supplement_cents": 88_000,
        "deposit_cents": 50_000,
    },
]

STANDARD_CANCELLATION_GRID = [
    {"min_days_before": 90, "penalty_bp": 1000},
    {"min_days_before": 60, "penalty_bp": 3500},
    {"min_days_before": 30, "penalty_bp": 6500},
    {"min_days_before": 0, "penalty_bp": 10000},
]

# A traveler on tier T1 with DOUBLE rooming and no deviation:
# gross 587000 -> grant 29350 (500bp) -> net 557650 -> fee 19518 -> total 577168.
HOLY_LAND_T1_INVOICE_CENTS = 577_168
HOLY_LAND_T1_PRICE_CENTS = 587_000
HOLY_LAND_DEPOSIT_CENTS = 50_000

# ---------------------------------------------------------------------------
# Product catalogue: two-tier small programme used for tier divergence
# ---------------------------------------------------------------------------

TWO_TIER_PRICE_TIERS = [
    {
        "tier_code": "P1",
        "min_pax": 1,
        "max_pax": 1,
        "per_pax_price_cents": 620_000,
        "single_supplement_cents": 105_000,
        "deposit_cents": 60_000,
    },
    {
        "tier_code": "P2",
        "min_pax": 2,
        "max_pax": 3,
        "per_pax_price_cents": 587_000,
        "single_supplement_cents": 98_000,
        "deposit_cents": 50_000,
    },
]

# ---------------------------------------------------------------------------
# Product catalogue: Rome Jubilee Deluxe (senior / high-value protection)
# ---------------------------------------------------------------------------

ROME_JUBILEE_TIERS = [
    {
        "tier_code": "RJ1",
        "min_pax": 1,
        "max_pax": 12,
        "per_pax_price_cents": 2_000_000,
        "single_supplement_cents": 300_000,
        "deposit_cents": 200_000,
    }
]

ROME_JUBILEE_GRID = [
    {"min_days_before": 60, "penalty_bp": 5000},
    {"min_days_before": 0, "penalty_bp": 10000},
]

# gross 2000000 -> grant 100000 -> net 1900000 -> fee 66500 -> total 1966500.
ROME_JUBILEE_INVOICE_CENTS = 1_966_500

# ---------------------------------------------------------------------------
# Product catalogue: Marian Shrines of Europe (grant-tier keying)
# ---------------------------------------------------------------------------

MARIAN_SHRINES_TIERS = [
    {
        "tier_code": "S1",
        "min_pax": 1,
        "max_pax": 14,
        "per_pax_price_cents": 299_000,
        "single_supplement_cents": 41_000,
        "deposit_cents": 30_000,
    },
    {
        "tier_code": "S2",
        "min_pax": 15,
        "max_pax": 30,
        "per_pax_price_cents": 268_000,
        "single_supplement_cents": 38_000,
        "deposit_cents": 30_000,
    },
]

MARIAN_SHRINES_GRID = [
    {"min_days_before": 45, "penalty_bp": 2500},
    {"min_days_before": 0, "penalty_bp": 10000},
]

# gross 299000 -> grant 0 (below 300000) -> net 299000 -> fee 10465 -> total 309465.
MARIAN_SHRINES_S1_INVOICE_CENTS = 309_465

__all__ = [name for name in dir() if not name.startswith("_")]
