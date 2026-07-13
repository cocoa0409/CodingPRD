"""Domain thresholds — numeric constants drawn from the PRD's business rules.

Generic NON_EXISTENT_UUID is imported from the framework, not redefined here.
"""

# Server boot / logical clock base (PRD §2.6)
CLOCK_BASE = "2026-03-01T00:00:00Z"

# Safety posture thresholds (PRD §2.7)
WARN_TEMP_C = 8.0
CLEAN_INTERVAL_SECONDS = 604800  # 7 days

# Cold-chain intake temperature bound (PRD §3.5)
MAX_SAFE_TEMP_C = 5.0

# Meal-impact conversion (PRD §3.5 / §3.9)
KG_PER_MEAL = 1.2

# Reimbursement ingredients (PRD §3.3)
BASE_STIPEND_CENTS = {"COVERAGE": 1500, "CLEANING": 2000}
RATE_LOW = 50    # cents/mile, first 5 miles
RATE_MID = 30    # cents/mile, miles 5..20
RATE_HIGH = 20   # cents/mile, beyond 20
COLD_CHAIN_BONUS_CENTS = 500
HAZARD_MULT = 1.25  # applied when posture is RESTRICTED at completion

# Steward double-booking travel buffer (PRD §3.3)
BUFFER_MINUTES = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}

# Food categories requiring a non-empty allergens list (PRD §3.5)
ALLERGEN_REQUIRED_CATEGORIES = {"BAKERY", "DAIRY", "PREPARED"}

# A well-formed UUID that no created resource will ever own.
FAKE_UUID = "00000000-0000-4000-8000-000000000000"
