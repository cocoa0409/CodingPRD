"""Domain thresholds and numeric constants drawn from the PRD's calculations."""

# The server's logical clock starts fixed here and never falls back to real time.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Pagination envelope bounds.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# Damage pricing: per-severity money multiplier and per-severity point weight.
SEVERITY_MULTIPLIER = {"MINOR": 1.00, "MODERATE": 1.25, "MAJOR": 1.60}
SEVERITY_POINTS = {"MINOR": 3, "MODERATE": 8, "MAJOR": 15}

# Deductible absorbed by the lessee before the carrier pays anything, by tier.
DEDUCTIBLE_CENTS_BY_TIER = {"A": 100_000, "B": 150_000, "C": 250_000}

# Administrative fee charged on the customer-liable slice.
ADMIN_FEE_PCT = 0.08

# A unit is out of service on damage at this many live points (inclusive).
OOS_DAMAGE_POINT_THRESHOLD = 25

# Underwriting / renewal risk scoring.
RISK_BASE_POINTS_BY_TIER = {"A": 10, "B": 25, "C": 45}
RISK_CHARGEBACK_BLOCK_CENTS = 10_000     # every full 10000 cents ...
RISK_POINTS_PER_BLOCK = 2                # ... adds two points
RISK_POINTS_PER_ASSESSMENT = 3
RISK_SCORE_MIN = 0
RISK_SCORE_MAX_CLAMP = 100               # reported score never above this
RISK_SCORE_SUBMIT_CEILING = 85           # 85 passes, 86 is rejected
RENEWAL_AGE_DISCOUNT_DAYS = 180          # strictly older than this halves the amount

# Depreciation and book value.
DEPRECIATION_RATE_PER_YEAR = 0.10
DEPRECIATION_MONTH_DAYS = 30
MONTHS_PER_YEAR = 12

# Lease-end purchase option.
MIN_PURCHASE_OPTION_TERM_DAYS = 720
LEASE_CREDIT_PCT = 0.12
LEASE_CREDIT_CAP_PCT = 0.30

# Settlement.
DROP_CHARGE_CENTS = 35_000
MILEAGE_PRORATION_BLOCK_DAYS = 30

# Repositioning move cost, a marginal waterfall.
RELOCATION_BASE_DISPATCH_FEE_CENTS = 15_000
RELOCATION_BAND_1_MAX_MILES = 250
RELOCATION_BAND_1_RATE_CENTS = 260
RELOCATION_BAND_2_MAX_MILES = 600
RELOCATION_BAND_2_RATE_CENTS = 215
RELOCATION_BAND_3_RATE_CENTS = 185
RELOCATION_DEADHEAD_RATE_CENTS = 130
RELOCATION_FUEL_SURCHARGE_PCT = 0.07
RELOCATION_FUEL_SURCHARGE_THRESHOLD_MILES = 500   # strict: 500 no, 501 yes
RELOCATION_MIN_CHARGE_CENTS = 40_000

# Inbound yard-capacity window, closed on both ends around planned_arrive_date.
INBOUND_WINDOW_DAYS_BEFORE = 1
INBOUND_WINDOW_DAYS_AFTER = 3

# Values reused across setups so expected figures stay reproducible.
TEST_DEFAULTS = {
    "BRANCH_CAPACITY": 10,
    "PEAK_START": "2026-09-01",
    "PEAK_END": "2026-11-30",
    "DAILY_RATE_CENTS": 5200,
    "PEAK_UPLIFT_PCT": 0.30,
    "MILEAGE_INCLUDED_PER_MONTH": 2500,
    "EXCESS_MILEAGE_RATE_CENTS_PER_MILE": 22,
    "ACQUISITION_COST_CENTS": 4_500_000,
    "RESIDUAL_FLOOR_CENTS": 450_000,
    "REQUIRED_PHYSICAL_DAMAGE_LIMIT_CENTS": 3_000_000,
    "DOT_INSPECTION_INTERVAL_DAYS": 365,
    "PM_INTERVAL_MILES": 30_000,
    "TRAILER_HUB_MILES": 41_000,
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "AGREEMENT_START_DATE": "2026-08-20",
    "AGREEMENT_END_DATE": "2026-09-10",
    "CHECKOUT_DATE": "2026-08-20",
    "RETURN_DATE": "2026-09-03",
    "RETURN_HUB_MILES": 42_000,
}
