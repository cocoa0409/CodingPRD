"""Domain constants for the airline ancillary merchandising API.

Every value here is fixed by the product requirements document: the basis-point
tables, the money-rounding rules, the offer lifecycle windows, the tax rates and
the channel incentive tiers.  Tests import these instead of hard-coding magic
numbers so that an assertion always reads in domain language.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Basis points
# ---------------------------------------------------------------------------
BP_ONE = 10000  # 10,000 basis points == a factor of 1

# ---------------------------------------------------------------------------
# Fare family valuation
# ---------------------------------------------------------------------------
CABIN_UPLIFT_BP = {
    "ECONOMY": 0,
    "PREMIUM": 1500,
    "BUSINESS": 3000,
}

CABIN_CLASSES = ("ECONOMY", "PREMIUM", "BUSINESS")
REFUNDABILITIES = ("NON_REFUNDABLE", "REFUNDABLE_WITH_FEE", "FULLY_REFUNDABLE")
FAMILY_STATUSES = ("DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED", "SUSPENDED", "RETIRED")

# ---------------------------------------------------------------------------
# Seat map pricing
# ---------------------------------------------------------------------------
ZONE_MULTIPLIER_BP = {
    "FWD": 13000,
    "MID": 10000,
    "AFT": 9000,
    "EXIT_ROW": 16000,
    "BULKHEAD": 14000,
}

ROW_BAND_ADJUST_CENTS = {
    "rows_1_to_5": 1500,
    "rows_6_to_15": 500,
    "rows_16_plus": 0,
}

SEAT_ZONES = ("FWD", "MID", "AFT", "EXIT_ROW", "BULKHEAD")

# ---------------------------------------------------------------------------
# Demand tiers
# ---------------------------------------------------------------------------
DEMAND_TIER_MULTIPLIER_BP = {
    "LOW": 10000,
    "MID": 11000,
    "HIGH": 12500,
}

DEMAND_TIER_THRESHOLD_PCT = {
    "HIGH_AT_OR_ABOVE": 80,
    "MID_AT_OR_ABOVE": 60,
}

DEMAND_TIERS = ("LOW", "MID", "HIGH")

# ---------------------------------------------------------------------------
# Willingness-to-pay scoring
# ---------------------------------------------------------------------------
BASE_WTP_BP = 10000
WTP_LF_SLOPE_BP = 40
WTP_SCARCITY_SLOPE_BP = 60
WTP_MIN_BP = 6000
WTP_MAX_BP = 16000

PRICING_VARIANTS = ("WTP_ELASTIC", "RESIDUAL_INVENTORY")

# ---------------------------------------------------------------------------
# Offer construction
# ---------------------------------------------------------------------------
TOUCHPOINT_MULTIPLIER_BP = {
    "BOOKING": 10000,
    "CHECKIN": 11000,
    "INFLIGHT": 12500,
}

TOUCHPOINTS = ("BOOKING", "CHECKIN", "INFLIGHT")

PRICE_FLOOR_BP = 7000
PRICE_CAP_BP = 18000
MAX_OFFERS_PER_SESSION = 3
OFFER_TTL_MINUTES = 60
OFFER_COOLOFF_MINUTES = 30

OFFER_STATUSES = ("PRESENTED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED")

# ---------------------------------------------------------------------------
# Ticketing allocation and the revenue ledger
# ---------------------------------------------------------------------------
CATEGORY_PRIORITY_ORDER = [
    "BAGGAGE",
    "SEAT",
    "CHANGE",
    "BOARDING",
    "ONBOARD",
    "AIR_TRANSPORT",
]

TAX_RATE_BP = {
    "TAXABLE_TRANSPORT": 750,
    "TAXABLE_SERVICE": 400,
    "EXEMPT": 0,
}

TAX_TREATMENTS = ("TAXABLE_TRANSPORT", "TAXABLE_SERVICE", "EXEMPT")
REVENUE_CLASSES = ("AIR_TRANSPORT_RELATED", "NON_AIR")
ENTRY_TYPES = ("ALLOCATION", "SALE", "REFUND", "WAIVER_CREDIT", "WAIVER_REVERSAL")

# ---------------------------------------------------------------------------
# Channel settlement
# ---------------------------------------------------------------------------
INCENTIVE_TIER_BP = {
    "at_or_above_50000": 300,
    "at_or_above_30000": 150,
    "below_30000": 0,
}

CHANNEL_TYPES = ("DIRECT", "GDS", "OTA", "NDC")
PARITY_STATES = ("PENDING", "IN_PARITY", "OUT_OF_PARITY", "WITHDRAWN")
DRIFT_REASONS = ("ATTRIBUTE_REPRICED", "FAMILY_REVISION_REJECTED", "FAMILY_SUSPENDED")
CONTENT_PARITY_STATUSES = ("COMPLIANT", "BREACHED")

# ---------------------------------------------------------------------------
# Irregular operations
# ---------------------------------------------------------------------------
IROPS_CHANGE_WAIVER_MIN_DELAY_MINUTES = 180
IROPS_EVENT_TYPES = ("DELAY", "CANCELLATION", "DIVERSION")
WAIVER_STATES = ("ACTIVE", "RESCINDED", "EXPIRED")
WAIVER_SCOPES = ("BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD")
IROPS_STATES = ("NORMAL", "IRREGULAR", "RECOVERED")
SALES_PHASES = ("PRESALE", "CHECKIN_OPEN", "BOARDING", "DEPARTED")

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

BOOKING_STATUSES = ("HELD", "TICKETED", "CHANGE_PENDING", "CANCELLED", "FLOWN")
DISCLOSURE_STATES = ("NOT_ISSUED", "PENDING_ACK", "ACKNOWLEDGED", "STALE")
ASSIGNMENT_STATES = ("HELD", "CONFIRMED", "RELEASED")
RELEASED_REASONS = ("PASSENGER_RELEASE", "BOOKING_CANCELLED", "IROPS_REACCOMMODATION")
PRODUCT_CATEGORIES = ("BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD")
AIR_TRANSPORT_CATEGORY = "AIR_TRANSPORT"
AIR_TRANSPORT_ACCOUNT_CODE = "3000"
AIR_TRANSPORT_SKU = "AIR_TRANSPORT"
CHANGE_SETTLEMENT_SKU = "CHANGE_SETTLEMENT"
CHANGE_SETTLEMENT_ACCOUNT_CODE = "4300"
