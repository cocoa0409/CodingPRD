"""Domain constants pinned by the PRD, plus payload defaults for the factories.

Every value here is copied from the PRD's own prose: the logical clock's startup
instant, the pagination envelope, and the pinned constants of the eight
calculations (earning, order pricing, award pricing, elite qualification, fraud
scoring, reaction risk and breakage).
"""

# --------------------------------------------------------------------------- #
# Logical clock and pagination
# --------------------------------------------------------------------------- #
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000fff"

# --------------------------------------------------------------------------- #
# Programme defaults
# --------------------------------------------------------------------------- #
DEFAULT_CURRENCY_CODE = "USD"
DEFAULT_CURRENT_PERIOD = "2026-08"
DEFAULT_BREAKAGE_POLICY_MODE = "HISTORICAL_ATTRITION"
DEFAULT_SAVER_SHARE_BPS = 3000

# --------------------------------------------------------------------------- #
# Issuer and agreement governance
# --------------------------------------------------------------------------- #
ISSUER_UTILIZATION_ALERT_BPS = 9000
MIN_AGREEMENT_TERM_DAYS = 90
VOLUME_TOLERANCE_BPS = 11000
AWARD_WINDOW_BUFFER_DAYS = 2

# --------------------------------------------------------------------------- #
# Earning credit with multipliers
# --------------------------------------------------------------------------- #
TIER_BONUS_BPS = {
    "BASE": 0,
    "SILVER": 2500,
    "GOLD": 5000,
    "PLATINUM": 10000,
}
CENTS_PER_CARD_SPEND_MILE = 100
CARD_SPEND_QUALIFYING_CAP_MILES = 15000
PER_MEMBER_BONUS_CAP_MILES = 25000
MIN_PROMOTION_MULTIPLIER_BPS = 10000
MAX_PROMOTION_MULTIPLIER_BPS = 50000

# --------------------------------------------------------------------------- #
# Award dynamic pricing
# --------------------------------------------------------------------------- #
DEMAND_MULTIPLIER_LADDER_BPS = {
    "EMPTY": 9000,
    "MODERATE": 10000,
    "BUSY": 12500,
    "PEAK": 16000,
}
LOAD_FACTOR_MODERATE_BPS = 5000
LOAD_FACTOR_BUSY_BPS = 7500
LOAD_FACTOR_PEAK_BPS = 9000
CAPACITY_CLOSED_LOAD_FACTOR_BPS = 10000

AWARD_CHART_MILES = {
    ("ECONOMY", "SAVER"): 12500,
    ("ECONOMY", "FLEX"): 25000,
    ("PREMIUM", "SAVER"): 25000,
    ("PREMIUM", "FLEX"): 45000,
    ("BUSINESS", "SAVER"): 50000,
    ("BUSINESS", "FLEX"): 85000,
    ("FIRST", "SAVER"): 90000,
    ("FIRST", "FLEX"): 140000,
}

PARTNER_UPLIFT_BPS = {
    "FIXED_CHART": 10000,
    "DISTANCE_BAND": 11500,
}

SURCHARGE_BAND_CENTS = {
    "SURCHARGE_LOW": 560,
    "SURCHARGE_MID": 1120,
    "SURCHARGE_HIGH": 2240,
}

MAX_SEATS_PER_BOOKING = 9
MIN_SEATS_PER_BOOKING = 1
HOLD_HOURS = 72

# --------------------------------------------------------------------------- #
# Partner settlement reciprocity factors
# --------------------------------------------------------------------------- #
RECIPROCITY_FACTOR_BPS = {
    "FULL": 10000,
    "INBOUND_ONLY": 10000,
    "OUTBOUND_ONLY": 5000,
}

# --------------------------------------------------------------------------- #
# Elite qualification and rollover
# --------------------------------------------------------------------------- #
ELITE_THRESHOLDS = {
    "SILVER": {"miles": 25000, "segments": 30, "spend_cents": 300000},
    "GOLD": {"miles": 75000, "segments": 75, "spend_cents": 900000},
    "PLATINUM": {"miles": 150000, "segments": 120, "spend_cents": 1500000},
}
ROLLOVER_CAP_MILES = 40000

# --------------------------------------------------------------------------- #
# Fraud risk and clawback
# --------------------------------------------------------------------------- #
GEO_VELOCITY_FACTOR = 10
REDEMPTION_VELOCITY_FACTOR = 20
BROKERING_FACTOR = 25
DORMANCY_DIVISOR = 4
SUB_SCORE_CAP = 100
FRAUD_WEIGHT_BPS = {
    "geo": 3500,
    "redemption": 3000,
    "brokering": 2500,
    "dormancy": 1000,
}
FREEZE_THRESHOLD = 70
WATCH_THRESHOLD = 40
CLAWBACK_LOOKBACK_DAYS = 90

# --------------------------------------------------------------------------- #
# Member reaction index
# --------------------------------------------------------------------------- #
CHANGE_TYPE_SEVERITY = {
    "AWARD_PRICING": 50,
    "EARN_STRUCTURE": 40,
    "ELITE_THRESHOLD": 30,
    "EXPIRY_POLICY": 20,
}
LEAD_TIME_FACTOR_BPS = {
    "LONG": 10000,
    "MEDIUM": 12500,
    "SHORT": 15000,
    "IMMEDIATE": 20000,
}
GRANDFATHER_RELIEF_FULL = 30
GRANDFATHER_RELIEF_PARTIAL = 15
GRANDFATHER_RELIEF_NONE = 0
EXPOSURE_BASE_BPS = 10000
EXPOSURE_BPS_PER_MEMBER = 100
EXPOSURE_BPS_CAP = 5000
REACTION_RISK_THRESHOLD = 70

# --------------------------------------------------------------------------- #
# Breakage and deferred revenue
# --------------------------------------------------------------------------- #
HISTORICAL_ATTRITION_FLOOR_BPS = 0
HISTORICAL_ATTRITION_CAP_BPS = 3500
FORWARD_EXPECTATION_FLOOR_BPS = 200
FORWARD_EXPECTATION_CAP_BPS = 3500
BREAKAGE_TRAILING_MONTHS = 24

# --------------------------------------------------------------------------- #
# Payload defaults used by the factories
# --------------------------------------------------------------------------- #
TEST_DEFAULTS = {
    "PROGRAM_NAME": "SkyMiles Loyalty",
    "CURRENT_PERIOD": "2026-08",
    "ISSUER_NAME": "Northbank Card Services",
    "ISSUER_CAP_MILES": 5_000_000,
    "TERM_START_DATE": "2026-09-01",
    "TERM_END_DATE": "2027-08-31",
    "COMMITTED_VOLUME_MILES": 1_000_000,
    "TIER_PRICE_CENTICENTS": 200,
    "MEMBER_REF": "MBR-0001",
    "HOME_REGION": "AMER",
    "ROUTE_CODE": "JFK-CDG",
    "CABIN": "ECONOMY",
    "WINDOW_START_DATE": "2026-09-01",
    "WINDOW_END_DATE": "2026-09-30",
    "AUTHORIZED_SEATS": 10,
    "TRAVEL_DATE": "2026-09-10",
    "IATA_CODE": "AF",
    "SETTLEMENT_RATE_CENTICENTS": 150,
    "CAMPAIGN_CODE": "PROMO-1",
    "CAMPAIGN_WINDOW_START": "2026-08-01T00:00:00Z",
    "CAMPAIGN_WINDOW_END": "2026-12-01T00:00:00Z",
}
