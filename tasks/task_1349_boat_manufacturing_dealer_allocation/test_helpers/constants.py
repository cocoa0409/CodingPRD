"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Logical clock (PRD §2.5): startup default, never wall-clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Order pricing (PRD §3.4).
SURCHARGE_RATE = 0.03
DISCOUNT_PREFERRED = 0.10
DISCOUNT_STANDARD = 0.05
DISCOUNT_PROBATION = 0.00

# Required deposit (PRD §3.4).
MIN_DEPOSIT_RATE = 0.03
MIN_DEPOSIT_CENTS = 50000
RATE_RETAIL = 0.10
RATE_FLEET = 0.15
STANDING_DELTA_PREFERRED = -0.02
STANDING_DELTA_STANDARD = 0.00
STANDING_DELTA_PROBATION = 0.05

# Floor-plan interest (PRD §3.7).
TIER_STANDARD_RATE = 0.06
TIER_ELEVATED_RATE = 0.075
TIER_HIGH_RATE = 0.095
TIER_ELEVATED_FLOOR = 0.50
TIER_HIGH_FLOOR = 0.80
INTEREST_DAY_COUNT_YEAR = 365

# Carrying cost at run close (PRD §3.3).
CARRYING_DAILY_RATE_CENTS = 750
SEASON_FACTOR_PEAK = 1.25
SEASON_FACTOR_SHOULDER = 1.00
SEASON_FACTOR_OFF_PEAK = 0.60

# Warranty claim reimbursement (PRD §3.8).
BASE_LABOR_RATE_CENTS = 9000
STANDARD_TIER1_HOURS = 2.0
STANDARD_TIER2_FACTOR = 0.85
STANDARD_PARTS_FACTOR = 0.85
COVERAGE_MONTHS = 36
REGISTRATION_WINDOW_DAYS = 45

# Restocking fee tiers (PRD §3.5).
RESTOCK_FEE_ALLOCATED = 0.05
RESTOCK_FEE_COMMITTED = 0.12

# HIN composition (PRD §3.6).
HIN_MIC = "BRW"
HIN_SERIAL_WIDTH = 5

# Canonical catalog fixtures shared by many tests.
CANONICAL_MODEL = {
    "model_code": "SP190",
    "model_name": "Sport 190",
    "model_year": 2027,
    "base_price_cents": 2500000,
    "length_feet": 19.5,
    "production_hours": 40,
}
CANONICAL_OPTION_TOWER = {
    "option_code": "WAKE-TOWER",
    "name": "Wake Tower",
    "price_cents": 350000,
    "production_hours": 6,
}
CANONICAL_OPTION_BALLAST = {
    "option_code": "BALLAST",
    "name": "Ballast System",
    "price_cents": 180000,
    "production_hours": 4,
}

# Pre-computed order totals for the canonical catalog at STANDARD standing
# (RETAIL source, 0.10 base rate, 0.05 line discount, 3% surcharge) —
# per PRD §3.4's pinned rounding order.
INVOICE_NO_OPTIONS = 2575000          # 2500000 + 0 + 75000
REQUIRED_NO_OPTIONS = 257500          # rhu(2575000 * 0.10)
INVOICE_TOWER = 2917475               # 2500000 + 332500 + 84975
REQUIRED_TOWER = 291748               # rhu(2917475 * 0.10)
INVOICE_BALLAST = 2751130             # 2500000 + 171000 + 80130
REQUIRED_BALLAST = 275113             # rhu(2751130 * 0.10)
INVOICE_TOWER_BALLAST = 3093605       # 2500000 + 503500 + 90105
REQUIRED_TOWER_BALLAST = 309361       # rhu(3093605 * 0.10)

# A deposit comfortably above any required amount used by the fixtures, for
# setup paths where the exact deposit is irrelevant to the assertion.
SAFE_DEPOSIT_CENTS = 10000000
