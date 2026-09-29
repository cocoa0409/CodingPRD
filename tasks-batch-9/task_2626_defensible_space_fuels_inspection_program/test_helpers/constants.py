"""Domain constants for the Defensible Space Fuels Inspection Program API.

Every literal in this module is transcribed from the PRD so that test files can
reference a named constant instead of an unexplained magic number.
"""

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

API_PREFIX = "/fire-district"

# "POST /_clock/set_current_utc" is mounted at the server root, outside the
# resource prefix.
CLOCK_PATH = "/_clock/set_current_utc"

# The PRD pins the initial logical clock value for every fresh server process.
EPOCH_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Envelope / pagination
# ---------------------------------------------------------------------------

REQUEST_ID_PREFIX = "req_"

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

# End-of-day deadline suffix: the PRD requires 23:59:59 UTC with zero
# fractional seconds for every derived deadline / expiry field.
END_OF_DAY_SUFFIX = "T23:59:59Z"

# ---------------------------------------------------------------------------
# Risk scoring (PRD risk scoring section)
# ---------------------------------------------------------------------------

SLOPE_SUBSCORE_MULTIPLIER = 2
SLOPE_SUBSCORE_CAP = 100

VEGETATION_POINTS = {
    "IRRIGATED_LANDSCAPE": 15,
    "GRASS": 40,
    "BRUSH": 75,
    "MIXED_CONIFER": 90,
}

ROOF_CLASS_POINTS = {
    "CLASS_A": 10,
    "CLASS_B": 45,
    "CLASS_C": 80,
    "NONE": 100,
}

ACCESS_CONSTRAINT_POINTS = {
    "NONE": 0,
    "GATED": 25,
    "DOG_ON_SITE": 40,
    "LOCKED_GATE": 60,
}

WEIGHT_SLOPE = 0.30
WEIGHT_VEGETATION = 0.30
WEIGHT_STRUCTURE = 0.25
WEIGHT_ACCESS = 0.15

HAZARD_ZONE_MULTIPLIER = {
    "MODERATE": 1.00,
    "HIGH": 1.15,
    "VERY_HIGH": 1.30,
}

RISK_SCORE_CAP = 100.00

RISK_CLASS_EXTREME_FLOOR = 75.0
RISK_CLASS_HIGH_FLOOR = 55.0
RISK_CLASS_MODERATE_FLOOR = 35.0

BASIS_INTAKE = "INTAKE_PROVISIONAL"
BASIS_VERIFIED = "POST_INSPECTION_VERIFIED"

# Intake provisional scoring always applies a zero hardening credit; the
# verified variant credits 4.00 points per compliant hardening finding and
# caps the total credit at 20.00.
INTAKE_HARDENING_CREDIT = 0.00
HARDENING_CREDIT_PER_COMPLIANT_FINDING = 4.00
HARDENING_CREDIT_CAP = 20.00

# Sentinel staleness used by the priority ranking when a parcel has never
# passed an inspection.
NEVER_PASSED_STALENESS_DAYS = 100000

# ---------------------------------------------------------------------------
# Zone grading (PRD zone evaluation section)
# ---------------------------------------------------------------------------

ZONE_BASE_CLEARANCE_FT = {
    "ZONE_0_EMBER": 5,
    "ZONE_1": 30,
    "ZONE_2": 100,
}

ZONE_POINT_WEIGHT = {
    "ZONE_0_EMBER": 1.50,
    "ZONE_1": 1.00,
    "ZONE_2": 0.60,
}

SLOPE_FACTOR_LOW = 1.00      # slope_pct < 20
SLOPE_FACTOR_MID = 1.25      # 20 <= slope_pct < 40
SLOPE_FACTOR_STEEP = 1.50    # slope_pct >= 40

SEVERITY_NONE_RATIO = 0.0000
SEVERITY_MINOR_MAX_RATIO = 0.2500
SEVERITY_MAJOR_MAX_RATIO = 0.6000

LADDER_FUEL_POINT_SURCHARGE = 8.00
ZONE_POINTS_CAP = 100.00

HARDENING_COMPLIANT_CREDIT_POINTS = 4.00
HARDENING_NON_COMPLIANT_CREDIT_POINTS = 0.00

MEASURED_VEG_POINTS_CAP = 100.00

ALL_ZONES = ("ZONE_0_EMBER", "ZONE_1", "ZONE_2")

# ---------------------------------------------------------------------------
# Violation notices (PRD notice section)
# ---------------------------------------------------------------------------

CERTIFIED_MAIL_SERVICE_DAYS = 5

BASE_COMPLIANCE_DAYS = {
    "MINOR": 60,
    "MAJOR": 30,
    "CRITICAL": 14,
}

VERY_HIGH_COMPRESSION_FACTOR = 0.75
MIN_COMPLIANCE_DAYS = 7

# Compressed values for a VERY_HIGH hazard parcel: ceil(base * 0.75), floored
# at the seven day minimum.
COMPRESSED_COMPLIANCE_DAYS = {
    "MINOR": 45,
    "MAJOR": 23,
    "CRITICAL": 11,
}

EXTENSION_DAYS = 30
MAX_EXTENSIONS = 1

VOID_REASON_SUPERSEDED = "SUPERSEDED_BY_NEW_NOTICE"

DEFAULT_NOTICE_LEAD_DAYS = 10
DEFAULT_INVOICE_DUE_DAYS = 45

# Notice states that count toward Parcel.open_violation_count.
OPEN_NOTICE_STATES = ("ISSUED", "EXTENDED", "OVERDUE", "ABATEMENT_AUTHORIZED")

# Inspection states that count toward Inspector.assigned_open_count.
LIVE_INSPECTION_STATES = ("SCHEDULED", "NOTICED", "ACCESS_DENIED")

MAX_ACCESS_DENIALS = 2

# ---------------------------------------------------------------------------
# Abatement and cost recovery (PRD abatement section)
# ---------------------------------------------------------------------------

ABATEMENT_CAP_CENTS = 750000

DISPOSAL_RATE_PER_TON_CENTS = 9200
ADMIN_OVERHEAD_PCT = 0.125

SUBSIDY_TIER_LOW_CEILING_CENTS = 100000    # pre-subsidy total < 100000
SUBSIDY_TIER_MID_CEILING_CENTS = 300000    # 100000 <= total < 300000
SUBSIDY_PCT_LOW_TIER = 0.30
SUBSIDY_PCT_MID_TIER = 0.20
SUBSIDY_PCT_HIGH_TIER = 0.10

# Ordered subsidy ladder used by the voluntary pre-compliance variant, which
# moves one rung more generous and saturates at the most generous rung.
SUBSIDY_LADDER = (SUBSIDY_PCT_HIGH_TIER, SUBSIDY_PCT_MID_TIER, SUBSIDY_PCT_LOW_TIER)

RECOVERY_BASIS_DISTRICT = "DISTRICT_CONTRACTED"
RECOVERY_BASIS_VOLUNTARY = "VOLUNTARY_PRECOMPLIANCE"

# Payment waterfall bucket order.
WATERFALL_BUCKETS = ("ADMIN_OVERHEAD", "MOBILIZATION", "DISPOSAL", "LABOR")

DEFAULT_MAX_DAILY_ORDERS = 2

CREW_HOUR_INCREMENT = 0.5

# Enrollment states whose reservations consume program budget.
BUDGET_CONSUMING_ENROLLMENT_STATES = ("APPROVED", "COMPLETED", "REIMBURSED")

# Enrollment states that make a parcel/program pair a live duplicate.
LIVE_ENROLLMENT_STATES = ("REQUESTED", "APPROVED", "WAITLISTED", "COMPLETED", "REIMBURSED")

# ---------------------------------------------------------------------------
# Support programs / cost share (PRD support program section)
# ---------------------------------------------------------------------------

COST_SHARE_ELIGIBLE_COST_CAP_CENTS = 250000
COST_SHARE_INVOICE_CAP_CENTS = 1000000

MATCH_PCT_BY_RISK_CLASS = {
    "EXTREME": 0.75,
    "HIGH": 0.60,
    "MODERATE": 0.45,
    "LOW": 0.30,
}

BONUS_TIER_LOW_CEILING_CENTS = 50000     # pre-bonus award < 50000
BONUS_TIER_MID_CEILING_CENTS = 120000    # 50000 <= pre-bonus award < 120000
BONUS_PCT_LOW_TIER = 0.15
BONUS_PCT_MID_TIER = 0.10
BONUS_PCT_HIGH_TIER = 0.05

PROGRAM_TYPE_GRANT = "COST_SHARE_GRANT"
PROGRAM_TYPE_CHIPPER = "CHIPPER_DAY"
PROGRAM_TYPE_CURBSIDE = "CURBSIDE_COLLECTION"

# ---------------------------------------------------------------------------
# Certificates and communities (PRD certificate section)
# ---------------------------------------------------------------------------

CERTIFICATE_VALIDITY_DAYS = 90

CERTIFICATE_ELIGIBLE_PARCEL_STATUSES = ("COMPLIANT", "EXEMPT")

COMMUNITY_MIN_MEMBER_PARCELS = 3
COMMUNITY_CERTIFY_RATE_FLOOR = 75.00
COMMUNITY_LAPSE_RATE_FLOOR = 60.00

MIN_SEASON_YEAR = 2020
MAX_SEASON_YEAR = 2100

# Compliance statuses included in the certified-rate denominator.
METRICS_ELIGIBLE_STATUSES = ("COMPLIANT", "NON_COMPLIANT", "ABATEMENT_PENDING")

# Compliance statuses excluded from both numerator and denominator.
METRICS_EXCLUDED_STATUSES = ("PENDING_INSPECTION", "EXEMPT")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

NON_EXISTENT_ID = "00000000-0000-0000-0000-0000000000ff"
