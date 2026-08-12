"""Global constants and enum member sets (PRD SCAFFOLD global_constants + PRD 2.x/3.x)."""
from decimal import Decimal

API_PREFIX = "/expediting"

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- business calendar -----------------------------------------------------
# Monday=0 .. Sunday=6 ; business week is MON..FRI
BUSINESS_WEEKDAYS = {0, 1, 2, 3, 4}
BUSINESS_DAY_START_HOUR_UTC = 9
BUSINESS_DAY_END_HOUR_UTC = 17
BUSINESS_DAY_MINUTES = 480

# --- service level tiers ---------------------------------------------------
STANDARD_SURCHARGE_PCT = Decimal("0.00")
EXPEDITED_SURCHARGE_PCT = Decimal("0.35")
RUSH_SURCHARGE_PCT = Decimal("0.80")
STANDARD_CUTOFF_HOUR_UTC = 21
EXPEDITED_CUTOFF_HOUR_UTC = 18
RUSH_CUTOFF_HOUR_UTC = 15
STANDARD_TURNAROUND_BUSINESS_DAYS = 15
EXPEDITED_TURNAROUND_BUSINESS_DAYS = 8
RUSH_TURNAROUND_BUSINESS_DAYS = 3
TIER_UPGRADE_ADMIN_FEE_CENTS = 2500

TIER_ORDER = {"STANDARD": 0, "EXPEDITED": 1, "RUSH": 2}
TIER_SURCHARGE = {
    "STANDARD": STANDARD_SURCHARGE_PCT,
    "EXPEDITED": EXPEDITED_SURCHARGE_PCT,
    "RUSH": RUSH_SURCHARGE_PCT,
}
TIER_CUTOFF_HOUR = {
    "STANDARD": STANDARD_CUTOFF_HOUR_UTC,
    "EXPEDITED": EXPEDITED_CUTOFF_HOUR_UTC,
    "RUSH": RUSH_CUTOFF_HOUR_UTC,
}
TIER_TURNAROUND_DAYS = {
    "STANDARD": STANDARD_TURNAROUND_BUSINESS_DAYS,
    "EXPEDITED": EXPEDITED_TURNAROUND_BUSINESS_DAYS,
    "RUSH": RUSH_TURNAROUND_BUSINESS_DAYS,
}

# --- order money -----------------------------------------------------------
ORDER_HANDLING_FEE_CENTS = 3000
MULTI_APPLICANT_MIN_COUNT = 3
MULTI_APPLICANT_DISCOUNT_PCT = Decimal("0.10")
MULTI_APPLICANT_WAIVER_FLOOR_CENTS = 20000
MAX_DISCOUNT_PCT = Decimal("0.25")
SPLIT_ADMIN_FEE_CENTS = 1500

# --- refund sliding schedule (keyed to Order.furthest_stage_reached) --------
REFUND_PCT_BY_STAGE = {
    "DRAFT": Decimal("1.00"),
    "QUOTED": Decimal("1.00"),
    "INTAKE": Decimal("0.75"),
    "READY_FOR_SUBMISSION": Decimal("0.50"),
    "SUBMITTED": Decimal("0.25"),
    "AT_AGENCY": Decimal("0.15"),
}

# --- document / photo / form prep ------------------------------------------
PASSPORT_VALIDITY_MONTHS_BEYOND_RETURN = 6
SUPPORTING_DOC_VALIDITY_DAYS = 90
DOCUMENT_RESUBMISSION_CAP = 2
PHOTO_VALIDITY_DAYS = 180
PHOTO_RETAKE_CAP = 3
PHOTO_MIN_HEAD_HEIGHT_RATIO = Decimal("0.50")
PHOTO_MAX_HEAD_HEIGHT_RATIO = Decimal("0.69")
PHOTO_MIN_RESOLUTION_PX = 600
MINOR_AGE_THRESHOLD_YEARS = 16

# --- consulate appointments -------------------------------------------------
APPOINTMENT_LEAD_TIME_HOURS = 48
APPOINTMENT_RESCHEDULE_CAP = 2
NO_SHOW_REBOOK_CAP = 2

# --- courier / custody -------------------------------------------------------
COURIER_LEG_BUSINESS_DAYS = 1
COURIER_REDISPATCH_CAP = 2

# --- agency RFE / decision ----------------------------------------------------
RFE_RESPONSE_BUSINESS_DAYS = 10
RFE_ROUND_CAP = 2

# --- feasibility / delivery ---------------------------------------------------
TRAVEL_DATE_BUFFER_DAYS = 5
DELIVERY_BUSINESS_DAYS = 2
DELIVERY_ATTEMPT_CAP = 3
DELIVERY_ESCALATION_THRESHOLD_DAYS = 7
DELIVERY_ESCALATION_FEE_CENTS = 4500

# ---------------------------------------------------------------------------
# Enum member sets
# ---------------------------------------------------------------------------
ROLES = [
    "PlatformAdmin",
    "CaseManager",
    "CourierOps",
    "AgencyLiaison",
    "ComplianceOfficer",
    "Traveler",
]
ROLES_REQUIRING_USER_ID = {
    "CaseManager",
    "Traveler",
    "ComplianceOfficer",
    "AgencyLiaison",
    "CourierOps",
}

VISA_TYPES = ["TOURIST", "BUSINESS", "STUDENT", "PASSPORT_RENEWAL", "PASSPORT_FIRST_TIME"]
GOVERNMENT_FEE_BASES = ["PER_APPLICANT", "PER_ORDER"]
DOC_TYPES = [
    "PASSPORT_BOOK",
    "PROOF_OF_TRAVEL",
    "INVITATION_LETTER",
    "BANK_STATEMENT",
    "VACCINATION_CERT",
    "EMPLOYMENT_LETTER",
    "PARENTAL_CONSENT",
]
VALIDITY_RULES = ["NONE", "EXPIRES_AFTER_ISSUE_DAYS", "VALID_BEYOND_RETURN_MONTHS"]
SERVICE_LEVELS = ["STANDARD", "EXPEDITED", "RUSH"]
BACKGROUND_CODES = ["WHITE", "OFF_WHITE", "COLORED"]
LEG_FROM_HOLDERS = ["APPLICANT", "SERVICE", "AGENCY"]
LEG_TO_HOLDERS = ["SERVICE", "AGENCY", "APPLICANT"]
SHIPMENT_METHODS = ["GROUND", "OVERNIGHT", "COURIER_SAME_DAY"]
REVIEW_DECISIONS = ["ACCEPT", "REJECT"]
LEG_OUTCOMES = ["DELIVERED", "FAILED"]
APPOINTMENT_OUTCOMES = ["ATTENDED", "NO_SHOW"]
RFE_ADJUDICATIONS = ["CLEARED", "INSUFFICIENT", "EXPIRED"]
AGENCY_DECISIONS = ["APPROVED", "REJECTED"]
PAYMENT_STREAMS = ["GOVERNMENT", "SERVICE"]

# Non-enum-routed (rung 6) sets
DELIVERY_ATTEMPT_OUTCOMES = ["DELIVERED", "FAILED"]

TERMINAL_WORKFLOW_STATES = {"COMPLETED", "CANCELLED", "ABANDONED"}

STAGE_RANK = {
    "DRAFT": 0,
    "QUOTED": 1,
    "INTAKE": 2,
    "READY_FOR_SUBMISSION": 3,
    "SUBMITTED": 4,
    "AT_AGENCY": 5,
}
