"""Domain thresholds — numeric constants drawn from the PRD calculations.

All monetary quantities are whole integer cents.
"""

# --- Meal penalty (PRD 3.5) --------------------------------------------------
MEAL_INTERVAL_HOURS = 6.0          # a meal must be called within every 6 worked hours
MEAL_FIRST_CENTS = 2500            # first missed meal
MEAL_NEXT_CENTS = 3500             # each additional missed meal

# --- Turnaround penalty (PRD 3.5) -------------------------------------------
MIN_TURNAROUND_HOURS = 10.0        # rest of >= 10h is compliant; < 10h breaches

# --- Overtime (actual pay) (PRD 3.5) ----------------------------------------
STANDARD_DAY_HOURS = 12.0
OVERTIME_MULTIPLIER = 1.5

# --- Residual tier schedule (PRD 3.9) ---------------------------------------
RESIDUAL_TIER1_CAP_CENTS = 100_000_000   # first 100,000,000 cents
RESIDUAL_TIER2_CAP_CENTS = 500_000_000   # cumulative up to 500,000,000 cents
RESIDUAL_TIER1_BPS = 120                 # 1.20%
RESIDUAL_TIER2_BPS = 180                 # 1.80%
RESIDUAL_TIER3_BPS = 240                 # 2.40%

# --- Pagination (PRD 2.3) ----------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- Shared test defaults ----------------------------------------------------
TEST_DEFAULTS = {
    "TOTAL_BUDGET_CENTS": 1_000_000,
    "SAG_DAILY_RATE_CENTS": 200_000,
    "SAG_FRINGE_RATE_BPS": 1800,
    "SAG_FRINGE_FLAT_CENTS": 15_000,
    "IATSE_DAILY_RATE_CENTS": 100_000,
    "IATSE_FRINGE_RATE_BPS": 1200,
    "IATSE_FRINGE_FLAT_CENTS": 8_000,
}
