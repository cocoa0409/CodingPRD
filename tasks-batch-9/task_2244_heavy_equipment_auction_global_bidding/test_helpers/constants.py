"""Domain thresholds and rate tables from the PRD's calculation narratives."""

# The logical clock's initial reading before any administrative set.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Condition grading weights and bands.
GRADE_WEIGHTS = {
    "structural_score": 0.35,
    "powertrain_score": 0.30,
    "hydraulics_score": 0.20,
    "tires_score": 0.15,
}
UNVERIFIED_METER_PENALTY = 15.0
UNVERIFIED_METER_BAND_CAP = "C"
GRADE_BAND_FLOORS = {"A": 85.0, "B": 70.0, "C": 55.0}

# Buyer geography.
TIER_A_COUNTRIES = ["US", "CA", "DE", "AU", "GB", "JP"]
TIER_B_COUNTRIES = ["MX", "AE", "BR", "ZA"]
EMBARGOED_COUNTRIES = ["IR", "KP", "SY", "RU"]

DEPOSIT_MINIMUM_BY_TIER = {
    "TIER_A": 100_000,
    "TIER_B": 500_000,
    "TIER_C": 1_500_000,
}
LEVERAGE_BY_TIER = {
    "TIER_A": 10,
    "TIER_B": 5,
    "TIER_C": 2,
}
FIRST_PADDLE_NUMBER = 101

# Bidding.
OPENING_BID_FLOOR_CENTS = 10_000

# Buyer premium.
LOW_VALUE_FLAT_RATE = 0.10
LOW_VALUE_FLAT_FLOOR_CENTS = 50_000
STANDARD_PREMIUM_TIERS = [
    (5_000_000, 0.12),
    (25_000_000, 0.08),
    (None, 0.05),
]
ONLINE_SURCHARGE_RATE = 0.015
VOLUME_DISCOUNT_HIGH_THRESHOLD_CENTS = 100_000_000
VOLUME_DISCOUNT_HIGH_RATE = 0.20
VOLUME_DISCOUNT_LOW_THRESHOLD_CENTS = 50_000_000
VOLUME_DISCOUNT_LOW_RATE = 0.10
PREMIUM_FLOOR_CENTS = 25_000
PREMIUM_CEILING_CENTS = 4_000_000

# Fixed invoice fees.
DOCUMENTATION_FEE_CROSS_BORDER_CENTS = 45_000
DOCUMENTATION_FEE_DOMESTIC_CENTS = 15_000
TITLE_TRANSFER_FEE_CENTS = 12_500
FINANCING_FEE_RATE = 0.02

# Tax.
TAX_RATES = {
    "US": 0.0625,
    "CA": 0.13,
    "MX": 0.16,
    "DE": 0.19,
    "AU": 0.10,
    "AE": 0.05,
    "GB": 0.20,
    "BR": 0.17,
    "JP": 0.10,
    "ZA": 0.15,
}
DEFAULT_TAX_RATE = 0.10

# Storage.
STORAGE_RATE_LIGHT_CENTS_PER_DAY = 2_500       # weight_kg <= 10000
STORAGE_RATE_MEDIUM_CENTS_PER_DAY = 6_000      # weight_kg <= 30000
STORAGE_RATE_HEAVY_CENTS_PER_DAY = 12_000      # heavier
STORAGE_LIGHT_WEIGHT_CEILING_KG = 10_000
STORAGE_MEDIUM_WEIGHT_CEILING_KG = 30_000
STORAGE_CAP_RATE_OF_HAMMER = 0.25

# Payment timing, by payment terms code.
PAYMENT_DUE_DAYS = {"PREPAY": 2, "NET_7": 7, "NET_30": 30}
GRACE_DAYS = {"PREPAY": 3, "NET_7": 5, "NET_30": 10}

# Remedies.
REOFFER_ADMIN_FEE_CENTS = 75_000
NO_SALE_FEE_CENTS = 25_000
DEFAULT_STRIKE_SUSPENSION_LIMIT = 2

# Consignor settlement commission schedules: marginal two-tier with a floor,
# the first tier running up to 10,000,000 cents of gross proceeds.
COMMISSION_TIER_BREAK_CENTS = 10_000_000
COMMISSION_SCHEDULES = {
    "RESERVE_STD": {"lower_rate": 0.12, "upper_rate": 0.09, "floor_cents": 100_000},
    "UNRESERVED_STD": {"lower_rate": 0.08, "upper_rate": 0.06, "floor_cents": 50_000},
}

# Iteration ceilings.
MAX_REWORK_ROUNDS = 2
MAX_COUNTER_ROUNDS = 3
MAX_PACKET_REOPENS = 2

# Fee waiver ceiling.
WAIVER_LIMIT_RATE_OF_SUBTOTAL = 0.05

# Listing defaults.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Convenient values reused across setups.
TEST_DEFAULTS = {
    "YARD_CODE": "YRD-DAL",
    "YARD_COUNTRY": "US",
    "TEARDOWN_BUFFER_MINUTES": 120,
    "LOADOUT_DEADLINE_DAYS": 10,
    "CURRENCY_CODE": "USD",
    "CANONICAL_HAMMER_CENTS": 12_000_000,
    "CANONICAL_WEIGHT_KG": 36_000,
    "CANONICAL_DEPOSIT_CENTS": 1_500_000,
}
