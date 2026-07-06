"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

THRESHOLDS = {
    # Claim line / order ledger
    "GA_COINSURANCE_RATE": 0.80,            # GA modifier pays statutory 80%
    # Warranty terms (calendar months)
    "PROSTHETIC_WARRANTY_MONTHS": 18,       # lower/upper-limb prosthetics
    "ORTHOSIS_WARRANTY_MONTHS": 12,         # all orthoses
    # Adjustment / repair windows
    "FREE_FITTING_DAYS": 90,                # free-fitting no-charge window
    "LABOR_FLAT_CENTS": 12500,              # flat labor fee for out-of-warranty repair
    # Prior auth
    "DECISION_DEADLINE_DAYS": 14,           # decision_deadline = clock + 14 days
    "RX_VALIDITY_MONTHS": 6,                # prescription 6-month validity window
    "RUL_YEARS": 5,                         # reasonable-useful-lifetime overlap window
}

# Server-startup default logical clock value.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# A well-formed UUID guaranteed not to resolve to any created resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Standard test clock baseline used by most fixtures.
TEST_CLOCK = "2026-06-01T00:00:00Z"
