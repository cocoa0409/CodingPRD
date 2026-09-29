"""Domain thresholds and numeric constants named by the PRD."""

from datetime import datetime, timezone

# ─── Logical clock (PRD §2.4) ─────────────────────────
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
OPEN_ENDED_SENTINEL = "9999-12-31T00:00:00Z"


def clock_stamp(instant: str) -> str:
    """Render a logical-clock instant the way a server-minted stamp reads back.

    PRD §2.4 pins the service's stamp format: "Every resource also carries
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits, read from
    the service's logical clock at the moment of creation", with `updated_at`
    "refreshed on every mutation using the same format", and every domain timestamp
    whose name ends in `_at` plus every `as_of` stamp "read from the logical clock"
    in exactly the same way. So a stamp taken at the instant `2026-08-01T00:00:00Z`
    reads back as `2026-08-01T00:00:00.000Z`, and a test that drove the clock to a
    bare-second instant must compare against that three-fractional-digit rendering.
    """
    text = instant.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )

# ─── Insurance (PRD §3.2) ─────────────────────────────
INSURANCE_COVERAGE_LIMIT_CENTS = 25_000_000

# ─── Capital tier lower bounds, inclusive (PRD §3.1) ──
WELL_CAPITALIZED_MIN_BPS = 1000
ADEQUATELY_CAPITALIZED_MIN_BPS = 800

# ─── Required collateral percentage (PRD §3.2) ────────
TIER_REQUIRED_PCT_BPS = {
    "WELL_CAPITALIZED": 10500,
    "ADEQUATELY_CAPITALIZED": 11000,
    "UNDERCAPITALIZED": 12500,
}
PLEDGING_MODE_SURCHARGE_BPS = {"DEDICATED": 0, "POOLED": 500}
DEFICIENCY_SURCHARGE_BPS = 1000
DEFICIENCY_SURCHARGE_TRIGGER_RUNS = 2
MAX_REQUIRED_PCT_BPS = 15000

# ─── Coverage boundary (PRD §3.2) ─────────────────────
SECURED_COVERAGE_RATIO_BPS = 10000

# ─── Haircuts by asset type (PRD §3.4) ────────────────
HAIRCUT_BPS_BY_TYPE = {
    "US_TREASURY": 200,
    "AGENCY_DEBENTURE": 300,
    "AGENCY_MBS": 800,
    "MUNI_GO": 1000,
    "MUNI_REVENUE": 1500,
    "LETTER_OF_CREDIT": 0,
}
INELIGIBLE_ASSET_TYPES = ["MUNI_REVENUE"]

# ─── Pool waterfall (PRD §3.5) ────────────────────────
POOL_PRIORITY_RANK_BY_UNIT_TYPE = {
    "SCHOOL_DISTRICT": 1,
    "COUNTY": 2,
    "MUNICIPALITY": 3,
    "STATE_AGENCY": 4,
}
DEFAULT_MINIMUM_POOL_PCT_BPS = 11000
MINIMUM_POOL_PCT_BPS_RANGE = (10000, 20000)

# ─── Custodian registration defaults (PRD §3.1) ───────
DEFAULT_CONCENTRATION_LIMIT_BPS = 6000
CONCENTRATION_LIMIT_BPS_RANGE = (1000, 10000)
DEFAULT_TRI_PARTY_CAPABLE = False

# ─── Depository registration defaults (PRD §3.1) ──────
DEFAULT_CAPITAL_RATIO_BPS = 1200
CAPITAL_RATIO_BPS_RANGE = (0, 5000)
DEFAULT_INSURANCE_DETERMINATION_BASIS = "AGGREGATED_BY_UNIT"

# ─── Collateral asset defaults (PRD §3.4) ─────────────
DEFAULT_MARKET_PRICE_BPS = 10000
PRICE_STALE_HOURS = 48

# ─── Qualification / amendment round ceilings ─────────
REVIEW_ROUND_LIMIT = 3
AMENDMENT_ROUND_LIMIT = 2
PLEDGE_CAPACITY_STATUTORY_CEILING_CENTS = 500_000_000_000

# ─── Mark-to-market (PRD §3.7) ────────────────────────
MTM_MIN_GAP_HOURS = 4
FROZEN_TRIGGER_RUNS = 3
CURE_DEADLINE_HOURS_BY_RATIO = [(2000, 24), (500, 48)]
CURE_DEADLINE_HOURS_DEFAULT = 120
ESCALATION_GRACE_HOURS = 24

# ─── Risk grading (PRD §3.7) ──────────────────────────
COVERAGE_COMPONENT_CAP_BPS = 12000
COVERAGE_COMPONENT_FLOOR_BPS = 9000
COVERAGE_COMPONENT_SPAN_BPS = 3000
VOLATILITY_PENALTY_BPS_PER_RUN = 2500
TRAILING_RUN_WINDOW = 3
WEIGHT_COVERAGE = 0.50
WEIGHT_VOLATILITY = 0.30
WEIGHT_DOCUMENTATION = 0.20
GRADE_A_MIN_BPS = 8500
GRADE_B_MIN_BPS = 7000
GRADE_C_MIN_BPS = 5000

# ─── Cure / reconciliation tolerances ─────────────────
CURE_OVERAGE_TOLERANCE_CENTS = 0
RECEIPT_DISCREPANCY_TOLERANCE_CENTS = 0

# ─── Pagination (PRD §2.3) ────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ─── Common test values ───────────────────────────────
TEST_DEFAULTS = {
    "STATUTORY_MAX_DEPOSIT_CENTS": 100_000_000_000,
    "REQUESTED_PLEDGE_CAPACITY_CENTS": 400_000_000_000,
    "DEPOSIT_CENTS": 100_000_000,
    "JURISDICTION_STATE": "OH",
}
