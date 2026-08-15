"""Domain thresholds and constants named in the PRD's calculation rules."""

DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Ocean freight charge (PRD §3.6)
    "BAF_PCT": 0.10,
    "THC_FCL_PER_CONTAINER_CENTS": 25000,
    "THC_LCL_PER_RT_CENTS": 1200,
    "DOC_FEE_CENTS": 7500,
    # ISF / AMS penalties (PRD §3.10)
    "ISF_LATE_PENALTY_CENTS": 500000,
    "AMS_LATE_PENALTY_CENTS": 300000,
    "MIN_BOND_AVAILABLE_CENTS": 75000,
    # Insurance (PRD §3.13)
    "MIN_PREMIUM_CENTS": 2500,
    "RATE_ALL_RISK": 0.006,
    "RATE_WA": 0.004,
    "RATE_FPA": 0.0025,
    "INSURED_MARKUP": 1.10,
    # Rollover / cancellation / caps (PRD §3.7, §3.11)
    "ROLLOVER_FEE_CENTS": 150000,
    "CANCELLATION_FEE_CENTS": 75000,
    "MAX_ROLLOVERS": 2,
    "MAX_AMENDMENTS": 3,
}

# Canonical scenario values shared by many fixtures. All timestamps are inside
# the default tariff / contract / bond windows so the logical clock (starting
# at 2026-08-01T00:00:00Z) never needs pre-adjustment for basic setup.
DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100000000,
    "LANE_ORIGIN": "CNSHA",
    "LANE_DESTINATION": "USLAX",
    "LANE": "CNSHA-USLAX",
    "LCL_RATE_PER_UNIT_CENTS": 9500,
    "LCL_MINIMUM_CHARGE_CENTS": 20000,
    "FCL_RATE_PER_UNIT_CENTS": 185000,
    "FCL_CONTAINER_TYPE": "40HC",
    "WINDOW_FROM": "2026-08-01T00:00:00Z",
    "WINDOW_TO": "2027-01-01T00:00:00Z",
    "CONTRACT_START": "2026-01-01T00:00:00Z",
    "CONTRACT_END": "2026-12-31T00:00:00Z",
    "BOND_COVERAGE_CENTS": 7500000,
    "VOYAGE_ETD": "2026-09-01T00:00:00Z",
    "VOYAGE_ETA": "2026-09-21T00:00:00Z",
    "ISF_DEADLINE": "2026-08-31T00:00:00Z",
    "AMS_DEADLINE": "2026-08-30T00:00:00Z",
    "DEMURRAGE_FREE_DAYS": 4,
    "DETENTION_FREE_DAYS": 3,
    "DETENTION_PER_DIEM_CENTS": 12000,
}

# Canonical demurrage tier table used by fixtures:
# days 1-3 @ 15000, days 4-7 @ 30000, days 8+ @ 60000.
DEFAULT_DEMURRAGE_TIERS = [
    {"from_day": 1, "to_day": 3, "per_diem_cents": 15000},
    {"from_day": 4, "to_day": 7, "per_diem_cents": 30000},
    {"from_day": 8, "to_day": None, "per_diem_cents": 60000},
]

# Canonical freight figures for the standard LCL booking
# (4000 kg / 6.0 cbm, CONTRACT 9500/RT, minimum 20000):
# RT = 6.0, base = 57000, BAF = 5700, THC = 7200, DOC = 7500.
LCL_BOOKING_WEIGHT_KG = 4000
LCL_BOOKING_VOLUME_CBM = 6.0
LCL_BOOKING_RT = 6.0
LCL_BOOKING_FREIGHT_CENTS = 77400

# Canonical figures for the standard FCL booking
# (1 x 40HC @ 185000, 18000 kg / 50.0 cbm):
# base = 185000, BAF = 18500, THC = 25000, DOC = 7500.
FCL_BOOKING_WEIGHT_KG = 18000
FCL_BOOKING_VOLUME_CBM = 50.0
FCL_BOOKING_CONTAINER_COUNT = 1
FCL_BOOKING_FREIGHT_CENTS = 236000

# Canonical insurance figures for cargo 5000000 on the standard LCL booking
# (freight base 57000): insured = (5000000 + 57000) * 1.10 = 5562700.
INSURED_CARGO_VALUE_CENTS = 5000000
INSURED_VALUE_CENTS = 5562700
PREMIUM_ALL_RISK_CENTS = 33376
PREMIUM_WA_CENTS = 22251
PREMIUM_FPA_CENTS = 13907
DEDUCTIBLE_ALL_RISK_CENTS = 55627
DEDUCTIBLE_FPA_CENTS = 111254
