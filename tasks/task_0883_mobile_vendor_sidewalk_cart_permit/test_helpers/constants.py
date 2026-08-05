"""Domain thresholds and numeric constants from the PRD's fee/settlement rules."""

# --- Insurance (Section 3.1) ---
MIN_INSURANCE_COVERAGE_CENTS = 100_000_000  # $1,000,000

# --- Permit fee (Section 3.4) ---
PERMIT_BASE_FEE_CENTS = 20_000
ZONE_SURCHARGE_CENTS = {"PRIME": 15_000, "STANDARD": 5_000}
CART_SIZE_FEE_CENTS = {"SMALL": 3_500, "MEDIUM": 6_500, "LARGE": 11_000}
FEE_TAX_RATE = 0.0875
RENEWAL_BASE_FACTOR = 0.80
RENEWAL_LATE_PENALTY_CENTS = 7_500
PERMIT_TERM_DAYS = 365
RENEWAL_GRACE_DAYS = 30

# --- Impound settlement (Section 3.9) ---
IMPOUND_BASE_FEE_CENTS = 10_000
IMPOUND_ADMIN_FEE_CENTS = 5_000
STORAGE_TIER1_DAYS = 7
STORAGE_DAILY_RATE1_CENTS = 2_500
STORAGE_DAILY_RATE2_CENTS = 4_000

# --- Violations (Section 3.7) ---
VIOLATION_POINTS = {"MINOR": 3, "MAJOR": 6, "CRITICAL": 12}
VIOLATION_FINE_CENTS = {"MINOR": 5_000, "MAJOR": 12_000, "CRITICAL": 30_000}
SUSPENSION_POINT_THRESHOLD = 12
VIOLATION_POINT_WINDOW_DAYS = 365

# --- Lottery ranking weights (Section 3.6) ---
LOTTERY_W_SENIORITY = 10
LOTTERY_W_COMPLIANCE = 1
LOTTERY_W_VIOLATION = 5

# --- Pre-computed expected amounts (STANDARD zone + MEDIUM cart of 30 sqft) ---
# base 20000 + zone 5000 + size 6500 + tax(1750+438+569=2757) = 34257
FEE_NEW_STANDARD_MEDIUM = 34_257
# base round(20000*0.80)=16000 + 5000 + 6500 + tax(1400+438+569=2407) = 29907
FEE_RENEWAL_EARLY_STANDARD_MEDIUM = 29_907
# NEW fee-shape 34257 + late penalty 7500 = 41757
FEE_RENEWAL_LATE_STANDARD_MEDIUM = 41_757

# --- Pre-computed impound settlement for a 10-day hold ---
# base 10000 + storage(7*2500 + 3*4000 = 29500) + admin 5000 = 44500
IMPOUND_RELEASE_10_DAYS = 44_500
# base 10000 + storage 29500 = 39500 (no admin fee, no vendor charge)
IMPOUND_FORFEIT_WRITEOFF_10_DAYS = 39_500

# --- Default logical clock the suites drive from ---
DEFAULT_TEST_CLOCK = "2026-06-01T00:00:00Z"
