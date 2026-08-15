"""Domain thresholds and shared fixtures values from the PRD."""

# Threshold constants (PRD §2.7, §3.4-§3.9)
MOISTURE_DRYING_REQUIRED_PCT = 10.49
MOISTURE_REJECT_PCT = 15.00
AFLATOXIN_PASS_MAX_PPB = 15.00
AFLATOXIN_SEGREGATE_MAX_PPB = 50.00
RETEST_MAX = 2
STRIKE_LIMIT = 2
CONTRACT_DEFAULT_LIMIT = 2
RESTRICTED_FREE_TONS = 500
RESTRICTED_MAX_LOAD_TONS = 50
LOAN_DAILY_INTEREST_BP = 2
MARGIN_FACTOR = 1.10
TURNAROUND_BUFFER_MIN = 120
SHRINK_ALLOWANCE_PCT = 0.01

# Logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT_MS = "2026-08-01T00:00:00.000Z"
DEFAULT_TEST_CLOCK = "2026-09-01T09:00:00Z"

# Standard buying point pricing (cents)
TEST_DEFAULTS = {
    "BP_NAME": "Tifton BP",
    "CROP_YEAR": 2026,
    "DRYING_RATE_PER_CYCLE_CENTS": 9000,
    "QUOTA_PRICE_CENTS_PER_TON": 56000,
    "ADDITIONAL_PRICE_CENTS_PER_TON": 40000,
    "LOAN_RATE_QUOTA_CENTS_PER_TON": 35500,
    "LOAN_RATE_ADDITIONAL_CENTS_PER_TON": 30000,
}

# FALL-2026 standard discount schedule shape
STANDARD_MOISTURE_TIERS = [
    {"up_to_pct": 8.0, "discount_cents_per_ton": 0},
    {"up_to_pct": 10.49, "discount_cents_per_ton": 250},
    {"up_to_pct": 12.0, "discount_cents_per_ton": 700},
    {"up_to_pct": 15.0, "discount_cents_per_ton": 1500},
    {"up_to_pct": None, "discount_cents_per_ton": 3000},
]
STANDARD_FM_TIERS = [
    {"up_to_pct": 4.0, "discount_cents_per_ton": 0},
    {"up_to_pct": 7.0, "discount_cents_per_ton": 400},
    {"up_to_pct": 10.0, "discount_cents_per_ton": 1000},
    {"up_to_pct": None, "discount_cents_per_ton": 2000},
]
STANDARD_DAMAGE_RATE_CENTS_PER_PCT = 150

# Reference load figures: 25.0t gross, m 9.2, fm 5.5, dmg 2.0, lsk 1.0
LOAD_A_GROSS_TONS = 25.0
LOAD_A_PAYABLE_TONS = 23.375
LOAD_A_DISCOUNT_CENTS = 22207
LOAD_A_GROSS_VALUE_CENTS = 1309000
LOAD_A_PROVISIONAL_CENTS = 1286793
LOAD_A_PRINCIPAL_CENTS = 887500
