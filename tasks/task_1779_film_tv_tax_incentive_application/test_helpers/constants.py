"""Domain thresholds and well-known values from the PRD.

The logical clock starts at DEFAULT_CLOCK_ISO on every fresh server. The
standard program configuration mirrors the GA FY2027 program used throughout
the domain narratives; override per test via the factories.
"""

# Logical clock fixed default (PRD: the clock starts at this fixed instant).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard GA FY2027 program configuration.
GA_PROGRAM_DEFAULTS = {
    "jurisdiction_code": "GA",
    "program_name": "GA Film Credit FY27",
    "fiscal_year": "FY2027",
    "window_opens_at": "2026-08-01T00:00:00Z",
    "window_closes_at": "2027-07-01T00:00:00Z",
    "annual_cap_cents": 100_000_000,
    "minimum_qualified_spend_cents": 10_000_000,
    "base_rate_standard": 0.25,
    "base_rate_elevated": 0.30,
    "elevated_tier_threshold_cents": 200_000_000,
    "atl_cap_pct": 0.40,
    "resident_uplift_pct": 0.025,
    "transfer_price_floor_pct": 0.90,
    "vendor_verification_validity_days": 365,
    "appeal_window_days": 30,
    "daily_interest_rate": 0.0005,
    "credit_validity_days": 1095,
    "transfer_proposal_validity_days": 14,
}

# Clawback assessment constants (PRD clawback section).
INTEREST_CAP_PCT = 0.5
AGGRAVATED_MULTIPLIER = 1.25

# Cash-flow projection constants (PRD estimation/projection section).
MILESTONE_WRAP_PCT = 0.40
MILESTONE_AUDIT_PCT = 0.30
MILESTONE_WRAP_LAG_DAYS = 0
MILESTONE_AUDIT_LAG_DAYS = 90
MILESTONE_ISSUANCE_LAG_DAYS = 180
CONSERVATIVE_SETTLEMENT_LAG_DAYS = 30

# Standard spend-ledger used by many scenarios: ATL 40M, BTL resident 100M
# (effective 102.5M at a 0.025 uplift), BTL 60M. System sums atl 40M /
# btl 162.5M; pre-cap 202.5M; ATL cap floor(0.40 * 202.5M) = 81M does not
# bind; capped 202.5M >= 200M tier; credit = round(202.5M * 0.30) = 60.75M.
STANDARD_ATL_CENTS = 40_000_000
STANDARD_BTL_CENTS = 162_500_000
STANDARD_CAPPED_CENTS = 202_500_000
STANDARD_CREDIT_CENTS = 60_750_000

# Standard production window.
STANDARD_START_DATE = "2026-09-01T00:00:00Z"
STANDARD_WRAP_DATE = "2026-12-15T00:00:00Z"
