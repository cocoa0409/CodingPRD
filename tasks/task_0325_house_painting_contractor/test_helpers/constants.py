"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Labor estimate (PRD §3.2)
PREP_FACTOR = {
    "LIGHT": 1.0,
    "STANDARD": 1.25,
    "HEAVY": 1.6,
    "RESTORATION": 2.0,
}
SQFT_PER_HOUR = 160
LABOR_RATE_CENTS_PER_HOUR = 6550

# Weather suitability (PRD §3.1)
MIN_EXTERIOR_TEMP_F = 50
MAX_EXTERIOR_PRECIP_PCT = 30

# Warranty payout (PRD §3.11)
TOUCHUP_LABOR_FRACTION = 0.20

# Project defaults (PRD §3.2)
DEFAULT_DEPOSIT_PCT = 30
DEFAULT_WARRANTY_MONTHS = 12

# Canonical fixture values used across the design indices.
# Product P1: price_per_gallon_cents=4000, coverage_sqft_per_gallon_per_coat=350.
PRODUCT_PRICE_PER_GALLON_CENTS = 4000
PRODUCT_COVERAGE_SQFT_PER_GALLON_PER_COAT = 350

# Pre-computed canonical line-item / project figures (see design index header):
#   S1 (120 sqft, 1 coat, LIGHT): gallons=1, material=4000, labor_raw=4912.5 -> labor=4913
#   S2 (100 sqft, 2 coats, LIGHT): gallons=1, material=4000, labor_raw=8187.5 -> labor=8188
TEST_DEFAULTS = {
    "S1_MATERIAL_CENTS": 4000,
    "S1_LABOR_CENTS": 4913,
    "S1_TOTAL_CENTS": 8913,
    "S1_DEPOSIT_30PCT_CENTS": 2674,        # round_half_up(8913 * 30 / 100) = 2674
    "S1_BALANCE_AFTER_DEPOSIT_CENTS": 6239,  # 8913 - 2674
    "S2_MATERIAL_CENTS": 4000,
    "S2_LABOR_CENTS": 8188,
    "S1_S2_ESTIMATE_MATERIAL_CENTS": 8000,
    "S1_S2_ESTIMATE_LABOR_CENTS": 13101,   # round-per-line THEN sum: 4913 + 8188
    "S1_S2_ESTIMATE_TOTAL_CENTS": 21101,
    "S1_S2_DEPOSIT_30PCT_CENTS": 6330,     # round_half_up(21101 * 30 / 100)
    "S1_S2_BALANCE_AFTER_DEPOSIT_CENTS": 14771,  # 21101 - 6330
    # ADD S3 (300 sqft, 2 coats, HEAVY): gallons=2, material=8000, labor=39300, delta=+47300
    "S3_MATERIAL_CENTS": 8000,
    "S3_LABOR_CENTS": 39300,
    "S3_ADD_DELTA_CENTS": 47300,
    # Warranty: provisional = round_half_up(0.20 * 4913) = 983 ; final(3.0h) = 19650
    "WARRANTY_PROVISIONAL_S1_CENTS": 983,
    "WARRANTY_FINAL_3H_CENTS": 19650,
}
