"""Domain thresholds — numeric constants from the PRD fee/SLA rules (§3.2, §3.3, §3.7)."""

# VALUATION fee tiers (integer cents)
VAL_T1_LIMIT_CENTS = 10_000_000      # $100,000
VAL_T1_RATE = 0.01
VAL_T2_LIMIT_CENTS = 50_000_000      # $500,000 cumulative
VAL_T2_RATE = 0.0075
VAL_T3_RATE = 0.005

# SQUARE_FOOTAGE per-sqft rates by building type (cents)
SQFT_RATE = {
    "RESIDENTIAL": 40,
    "COMMERCIAL": 55,
    "INDUSTRIAL": 45,
    "ESSENTIAL_FACILITY": 70,
}

MIN_BASE_FEE_CENTS = 50_000          # five-hundred-dollar floor

SCOPE_MULT = {
    "FULL_REVIEW": 1.0,
    "LATERAL_ONLY": 0.6,
    "PEER_REVIEW": 0.8,
}

EXPEDITE_SURCHARGE_RATE = 0.5
RESUBMITTAL_FEE_CENTS = 75_000
DEFERRED_ITEM_FEE_RATE = 0.05

# Logical clock default reading before any operator sets it (PRD §2.8)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Default registered capacity for a reviewer (PRD §3.1)
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 3

# Default jurisdiction knobs when omitted (PRD §3.1)
DEFAULT_FREE_RESUBMITTAL_CYCLES = 2
DEFAULT_REQUIRES_SE_SEAL = False
DEFAULT_ALLOWS_DEFERRED_SUBMITTALS = True

DEFAULT_APPLICANT_ID = "app-1"

TEST_DEFAULTS = {
    "VALUATION_CENTS": 30_000_000,
    "FLOOR_AREA_SQFT": 10_000,
    "TURNAROUND_DAYS": 15,
}
