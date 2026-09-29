"""Numeric and textual constants transcribed from the PRD.

Nothing here is invented: every table, floor and default below is quoted from a
sentence of the specification, and the tests reference these names instead of
repeating magic numbers.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import List

# --- Routing (PRD 4) --------------------------------------------------------

BASE = "/resilience"

# --- Logical clock (PRD 2.4) -----------------------------------------------
# "the logical clock starts at 2026-08-01T00:00:00Z" and never advances on its
# own.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_STAMP = "2026-08-01T00:00:00.000Z"

# --- Pagination (PRD 2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Jurisdiction (PRD 3.1) ------------------------------------------------
SVI_TIER_SEVERE_FLOOR = Decimal("0.75")
SVI_TIER_HIGH_FLOOR = Decimal("0.50")
SVI_TIER_MODERATE_FLOOR = Decimal("0.25")
DISADVANTAGED_TIERS: List[str] = ["HIGH", "SEVERE"]
DEFAULT_ENDORSEMENT_WEIGHT = 1

# --- Vulnerability scoring (PRD 3.3) ---------------------------------------
SVI_MULTIPLIER = {
    "LOW": Decimal("1.00"),
    "MODERATE": Decimal("1.10"),
    "HIGH": Decimal("1.25"),
    "SEVERE": Decimal("1.40"),
}
SVI_MULTIPLIER_WITHOUT_OVERLAY = Decimal("1.00")
SUBJECT_TYPE_UPLIFT = {
    "INFRASTRUCTURE": Decimal("0.00"),
    "POPULATION": Decimal("0.05"),
    "ECONOMIC_SECTOR": Decimal("0.03"),
}
ADDITIVE_EXPOSURE_WEIGHT = Decimal("0.40")
ADDITIVE_SENSITIVITY_WEIGHT = Decimal("0.35")
ADDITIVE_CAPACITY_WEIGHT = Decimal("0.25")
VULNERABILITY_BAND_EXTREME_FLOOR = Decimal("0.75")
VULNERABILITY_BAND_HIGH_FLOOR = Decimal("0.50")
VULNERABILITY_BAND_MODERATE_FLOOR = Decimal("0.25")

# --- Criticality ranking (PRD 3.4) -----------------------------------------
MILLION_DOLLARS_IN_CENTS = 100000000
CASCADE_FACTOR_STEP = Decimal("0.15")
CASCADE_FACTOR_MAX_HOPS = 3
SHARED_ASSET_FACTOR = Decimal("1.20")
UNSHARED_ASSET_FACTOR = Decimal("1.00")
POPULATION_WEIGHT_CAP = 250000
TIER_1_FLOOR = Decimal("25.00")
TIER_2_FLOOR = Decimal("8.00")
TIER_POINTS = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("0.60"),
    "TIER_3": Decimal("0.30"),
}

# --- Screening cost stack (PRD 3.5) ----------------------------------------
ESCALATION_BPS = {
    "PROTECT": 1200,
    "ACCOMMODATE": 800,
    "RETREAT": 1500,
    "AVOID": 500,
}
# Bands keyed on the Step 1 result, never on the eventual total.
ADMIN_RATE_BAND_LOW_CEILING_CENTS = 50000000      # five hundred thousand dollars
ADMIN_RATE_BAND_MID_CEILING_CENTS = 500000000     # five million dollars
ADMIN_RATE_BPS_LOW_BAND = 900
ADMIN_RATE_BPS_MID_BAND = 600
ADMIN_RATE_BPS_HIGH_BAND = 350
# Bands keyed on total_program_cost_cents.
MATCH_BAND_LOW_CEILING_CENTS = 100000000          # one million dollars
MATCH_BAND_MID_CEILING_CENTS = 1000000000         # ten million dollars
MATCH_SHARE_BPS_LOW_BAND = 2500
MATCH_SHARE_BPS_MID_BAND = 3000
MATCH_SHARE_BPS_HIGH_BAND = 3500
SCREEN_COST_NORMALIZER_CENTS = 200000000          # two million dollars
SCREEN_COST_WEIGHT = Decimal("0.40")
SCREEN_COBENEFIT_WEIGHT = Decimal("0.25")
SCREEN_FEASIBILITY_WEIGHT = Decimal("0.35")
MAX_COBENEFIT_POINTS = 20
SCREEN_IN_FLOOR = Decimal("0.4500")

# --- Benefit-cost analysis (PRD 3.6) ---------------------------------------
DEFAULT_DISCOUNT_RATE_BPS = 700
MIN_DISCOUNT_RATE_BPS = 1
MAX_DISCOUNT_RATE_BPS = 2000
OM_BURDEN_RATE = Decimal("0.02")
BCR_GRANT_FLOOR = Decimal("1.0000")

# --- Capital programming (PRD 3.7) -----------------------------------------
MIN_FISCAL_YEAR = 2026
MAX_FISCAL_YEAR = 2040
DEFAULT_EQUITY_TARGET_BPS = 4000
PRIORITY_RATIO_WEIGHT = Decimal("0.45")
PRIORITY_CRITICALITY_WEIGHT = Decimal("0.30")
PRIORITY_EQUITY_WEIGHT = Decimal("0.25")
PRIORITY_BCR_CAP = Decimal("3.0000")
OVERSUBSCRIBED_HEADROOM_BPS = 1000
LEDGER_COMMITTED_STATUSES: List[str] = ["PROGRAMMED", "GRANT_SUBMITTED", "AWARDED"]
ON_TRACK_FLOOR = Decimal("90.00")
AT_RISK_FLOOR = Decimal("70.00")

# --- Plan cycles and endorsement (PRD 3.8) ---------------------------------
DEFAULT_QUORUM_WEIGHT_BPS = 6600
DEFAULT_MAX_REVISION_ROUNDS = 2
DEFAULT_REQUIRED_SESSION_COUNT = 2
SESSION_BUFFER_HOURS = 24
VETO_BLOCKING_WEIGHT = 3
LIVE_DECISIONS: List[str] = ["ENDORSED", "CONDITIONED", "VETOED"]

# --- Mutual aid (PRD 3.9) --------------------------------------------------
DEFAULT_MAX_CONCURRENT_COMMITMENTS = 3
MIN_MAX_CONCURRENT_COMMITMENTS = 1
MAX_MAX_CONCURRENT_COMMITMENTS = 20
ACTIVE_COMMITMENT_STATUSES: List[str] = ["COMMITTED", "FULFILLED"]

# --- Shared helpers --------------------------------------------------------

BPS_DENOMINATOR = 10000


def round_half_up(value: Decimal, places: int) -> Decimal:
    """Round half up to `places` fractional digits, per PRD 2.6."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_bps(numerator: int, denominator: int) -> int:
    """Ten thousand times a ratio, floored to whole basis points (PRD 2.6)."""
    if denominator == 0:
        return 0
    return (BPS_DENOMINATOR * numerator) // denominator
