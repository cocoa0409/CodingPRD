"""Business constants transcribed from the PRD.

Every literal here is stated explicitly in the PRD; nothing is inferred.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
# "Until the clock is set for the first time, it reads 2026-08-01T00:00:00Z."
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_MS = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_CARE_AGENT = "CareAgent"
ROLE_CARE_SUPERVISOR = "CareSupervisor"
ROLE_QUALITY_LEAD = "QualityLead"
ROLE_REGULATORY_OFFICER = "RegulatoryOfficer"
ROLE_CONSUMER = "Consumer"

# StaffUser.role values, and the X-User-Role token each one acts under.
STAFF_ROLE_CARE_AGENT = "CARE_AGENT"
STAFF_ROLE_CARE_SUPERVISOR = "CARE_SUPERVISOR"
STAFF_ROLE_QUALITY_LEAD = "QUALITY_LEAD"
STAFF_ROLE_REGULATORY_OFFICER = "REGULATORY_OFFICER"

HEADER_ROLE_FOR_STAFF_ROLE = {
    STAFF_ROLE_CARE_AGENT: ROLE_CARE_AGENT,
    STAFF_ROLE_CARE_SUPERVISOR: ROLE_CARE_SUPERVISOR,
    STAFF_ROLE_QUALITY_LEAD: ROLE_QUALITY_LEAD,
    STAFF_ROLE_REGULATORY_OFFICER: ROLE_REGULATORY_OFFICER,
}

AUTHORITY_TIERS = ("TIER_1", "TIER_2", "TIER_3")
AUTHORITY_TIER_RANK = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}

# --------------------------------------------------------------------------
# Enumerations (PRD 3.1 - 3.9)
# --------------------------------------------------------------------------
PLANT_REGIONS = ("MW", "NE", "SE", "WEST")
PRODUCT_CATEGORIES = ("SNACK", "BEVERAGE", "DAIRY", "NON_FOOD")
CONTACT_CHANNELS = ("PHONE", "EMAIL", "SOCIAL", "WEB")
COMPLAINT_TYPES = ("FOREIGN_MATERIAL", "ILLNESS", "PACKAGING", "QUALITY")
FOREIGN_OBJECT_CLASSES = ("NONE", "SOFT", "HARD_BLUNT", "HARD_SHARP")
REMEDY_TYPES = ("COUPON", "REFUND", "REPLACEMENT")
REPORT_KINDS = ("ADVERSE_EVENT", "ILLNESS_CLUSTER", "FOREIGN_MATERIAL_INJURY")
SCOPE_LEVELS = ("LOT", "LINE", "PLANT")
SEVERITY_BANDS = ("S1", "S2", "S3", "S4")
OVERSIGHT_POSTURES = ("NORMAL", "WATCH", "INVESTIGATION_HOLD")

# --------------------------------------------------------------------------
# Provisional severity scoring (PRD 3.2)
# --------------------------------------------------------------------------
COMPLAINT_TYPE_WEIGHT = {
    "FOREIGN_MATERIAL": 40,
    "ILLNESS": 50,
    "PACKAGING": 20,
    "QUALITY": 10,
}
FOREIGN_OBJECT_WEIGHT = {
    "NONE": 0,
    "SOFT": 5,
    "HARD_BLUNT": 15,
    "HARD_SHARP": 30,
}
MEDICAL_ATTENTION_POINTS = 25
HOSPITALIZATION_POINTS = 35
PER_SYMPTOM_POINTS = 3.5
MAX_SCORING_SYMPTOMS = 4
MAX_SYMPTOM_CODES = 12

# Band thresholds (PRD 3.2): S1 at or above 90, else S2 at or above 60,
# else S3 at or above 30, else S4.
BAND_S1_MIN = 90
BAND_S2_MIN = 60
BAND_S3_MIN = 30

# --------------------------------------------------------------------------
# Adjudicated severity multipliers (PRD 3.3), applied sequentially
# --------------------------------------------------------------------------
VULNERABILITY_MULTIPLIER = 1.15
REGULATED_FOOD_MULTIPLIER = 1.075

# --------------------------------------------------------------------------
# Goodwill remedy arithmetic (PRD 3.6)
# --------------------------------------------------------------------------
REQUESTED_VALUE_MIN_CENTS = 1
REQUESTED_VALUE_MAX_CENTS = 999_999
SAMPLE_RETURN_CREDIT_CENTS = 799
REPLACEMENT_UNIT_CAP = 3
REPLACEMENT_HANDLING_FACTOR = 1.15

UPLIFT_BAND_LOW_MAX_EXCLUSIVE = 1_000     # base below 1,000 draws 0.00
UPLIFT_BAND_MID_MAX_EXCLUSIVE = 5_000     # 1,000 .. 4,999 draws 0.10
UPLIFT_PCT_LOW = 0.00
UPLIFT_PCT_MID = 0.10
UPLIFT_PCT_HIGH = 0.05

TIER_1_MAX_PAYOUT_CENTS = 2_500
TIER_2_MAX_PAYOUT_CENTS = 7_500
GOODWILL_MAX_PAYOUT_CENTS = 25_000
REVISION_CAP = 2

# --------------------------------------------------------------------------
# Sentiment index (PRD 3.6)
# --------------------------------------------------------------------------
SENTIMENT_BASELINE = 50.00
SENTIMENT_WINDOW_DAYS = 180
SENTIMENT_PENALTY = {"S1": 20, "S2": 12, "S3": 6, "S4": 3}
PROVISIONAL_SURCHARGE = 5
DECAY_AGE_DAYS = 90
DECAY_FACTOR = 0.5
CREDIT_PER_FULFILLED_REMEDY = 8
CREDIT_PER_RESPONDED_COMPLAINT = 4
SENTIMENT_MIN = 0.00
SENTIMENT_MAX = 100.00
SENTIMENT_VIEW_AGENT = "agent_view"
SENTIMENT_VIEW_EXECUTIVE = "executive_view"

# --------------------------------------------------------------------------
# Sample kit custody and occupancy (PRD 3.5)
# --------------------------------------------------------------------------
CUSTODY_SEQUENCE = (
    "KIT_ISSUED",
    "CONSUMER_SEALED",
    "CARRIER_PICKUP",
    "LAB_RECEIVED",
    "LAB_OPENED",
)
CUSTODY_CHAIN_LENGTH = 5
RETURN_WINDOW_DAYS = 14
OCCUPANCY_LEAD_HOURS = 48
OCCUPANCY_TRAIL_HOURS = 48
MAX_TRANSIT_HOURS = 240.00
OPEN_KIT_STATUSES = ("REQUESTED", "SHIPPED", "IN_TRANSIT_INBOUND", "RECEIVED")

# --------------------------------------------------------------------------
# Regulatory deadlines (PRD 3.7)
# --------------------------------------------------------------------------
S1_DEADLINE_HOURS = 24
DEFAULT_DEADLINE_HOURS = 72

# --------------------------------------------------------------------------
# Trend detection (PRD 3.9)
# --------------------------------------------------------------------------
DETECTION_WINDOW_DAYS = 30
MIN_WEIGHTED_COUNT = 3.0
THRESHOLD_PPM = {"LOT": 25.0, "LINE": 12.0, "PLANT": 6.0}
TREND_SEVERITY_WEIGHT = {"S1": 3, "S2": 2, "S3": 1, "S4": 0}
RATE_VARIANT_PROVISIONAL = "provisional"
RATE_VARIANT_ADJUDICATED = "adjudicated"

# --------------------------------------------------------------------------
# Canonical fixture literals reused across the suite
# --------------------------------------------------------------------------
CRACKER_SKU = "SKU-CRACKER"
CRACKER_NAME = "Sea Salt Crackers"
CRACKER_CATEGORY = "SNACK"
CRACKER_PRICE_CENTS = 2500
CRACKER_UNITS_PER_CASE = 12
CRACKER_IS_REGULATED = True

MUG_SKU = "SKU-MUG"
MUG_NAME = "Ceramic Mug"
MUG_CATEGORY = "NON_FOOD"
MUG_PRICE_CENTS = 1800
MUG_UNITS_PER_CASE = 6
MUG_IS_REGULATED = False

CANONICAL_BATCH_CODE = "A1B-2026-0710"
CANONICAL_NORMALIZED_BATCH_CODE = "A1B20260710"
CANONICAL_CODE_DATE = "2026-07-10T00:00:00Z"
CANONICAL_UNITS_PRODUCED = 200_000
