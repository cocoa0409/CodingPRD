"""Domain constants declared verbatim in SCAFFOLD.yaml / PRD.md."""
from decimal import Decimal

API_PREFIX = "/peds"

# ---- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# ---- roles -----------------------------------------------------------------
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_PHYSICIAN = "Physician"
ROLE_CARE_COORDINATOR = "CareCoordinator"
ROLE_BILLING_SPECIALIST = "BillingSpecialist"
ROLE_PARENT = "Parent"
ALL_ROLES = [
    ROLE_PRACTICE_ADMIN,
    ROLE_PHYSICIAN,
    ROLE_CARE_COORDINATOR,
    ROLE_BILLING_SPECIALIST,
    ROLE_PARENT,
]

# ---- pagination ------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ---- immunization ----------------------------------------------------------
IMMUNIZATION_GRACE_DAYS = 4
IMMUNIZATION_DUE_LAG_DAYS = 30

VACCINE_SCHEDULE = {
    "HEPB": {
        "total_doses": 3,
        "positions": [
            {"series_index": 1, "min_age_days": 0, "min_interval_days": None},
            {"series_index": 2, "min_age_days": 28, "min_interval_days": 28},
            {"series_index": 3, "min_age_days": 168, "min_interval_days": 56},
        ],
    },
    "DTAP": {
        "total_doses": 5,
        "positions": [
            {"series_index": 1, "min_age_days": 42, "min_interval_days": None},
            {"series_index": 2, "min_age_days": 70, "min_interval_days": 28},
            {"series_index": 3, "min_age_days": 98, "min_interval_days": 28},
            {"series_index": 4, "min_age_days": 365, "min_interval_days": 168},
            {"series_index": 5, "min_age_days": 1460, "min_interval_days": 168},
        ],
    },
}
VACCINE_CODES = ["HEPB", "DTAP"]
VALIDITY_VALUES = ["VALID", "INVALID"]
INVALID_REASONS = [
    "MIN_AGE_NOT_MET",
    "MIN_INTERVAL_NOT_MET",
    "SERIES_ALREADY_COMPLETE",
    "MANUALLY_INVALIDATED",
]

# ---- well-visit periodicity -------------------------------------------------
WELL_VISIT_SCHEDULE = [
    {"milestone_code": "NEWBORN", "target_age_days": 5, "window_open_offset_days": 3, "window_close_offset_days": 7},
    {"milestone_code": "M1", "target_age_days": 30, "window_open_offset_days": 23, "window_close_offset_days": 44},
    {"milestone_code": "M2", "target_age_days": 61, "window_open_offset_days": 53, "window_close_offset_days": 75},
    {"milestone_code": "M4", "target_age_days": 122, "window_open_offset_days": 114, "window_close_offset_days": 136},
    {"milestone_code": "M6", "target_age_days": 183, "window_open_offset_days": 175, "window_close_offset_days": 197},
    {"milestone_code": "M9", "target_age_days": 274, "window_open_offset_days": 259, "window_close_offset_days": 289},
    {"milestone_code": "M12", "target_age_days": 365, "window_open_offset_days": 350, "window_close_offset_days": 380},
    {"milestone_code": "M24", "target_age_days": 730, "window_open_offset_days": 700, "window_close_offset_days": 760},
    {"milestone_code": "M36", "target_age_days": 1095, "window_open_offset_days": 1065, "window_close_offset_days": 1125},
    {"milestone_code": "M48", "target_age_days": 1460, "window_open_offset_days": 1430, "window_close_offset_days": 1490},
    {"milestone_code": "M60", "target_age_days": 1825, "window_open_offset_days": 1795, "window_close_offset_days": 1855},
]
MILESTONE_CODES = [m["milestone_code"] for m in WELL_VISIT_SCHEDULE]
WELL_VISIT_MISS_GRACE_DAYS = 30
WELL_VISIT_STATUSES = ["DUE", "SCHEDULED", "COMPLETED", "MISSED", "CANCELLED"]
PUNCTUALITY_VALUES = ["EARLY", "ON_SCHEDULE", "DELAYED"]

# ---- panel capacity ---------------------------------------------------------
INFANT_SLOT_WEIGHT = 2.0
TODDLER_SLOT_WEIGHT = 1.5
STANDARD_SLOT_WEIGHT = 1.0
INFANT_SLOT_WEIGHT_MAX_AGE_DAYS = 365
TODDLER_SLOT_WEIGHT_MAX_AGE_DAYS = 1095
SLOT_WEIGHT_DECIMAL_PLACES = 1
WAITLIST_ENTRY_TTL_DAYS = 90
WAITLIST_STATUSES = ["WAITING", "PROMOTED", "WITHDRAWN", "EXPIRED"]

# ---- sibling / family pricing ----------------------------------------------
SIBLING_DISCOUNT_TIER_1_PCT = Decimal("0.00")
SIBLING_DISCOUNT_TIER_2_PCT = Decimal("0.20")
SIBLING_DISCOUNT_TIER_3_PLUS_PCT = Decimal("0.35")
MONEY_DECIMAL_PLACES = 0
INVOICE_DUE_DAYS = 14
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PAID"]

# ---- entitlements ------------------------------------------------------------
MEMBERSHIP_YEAR_DAYS = 365
BENEFIT_TYPES = ["LACTATION_CONSULT", "SLEEP_CONSULT"]
GRANT_STATUSES = ["OPEN", "EXHAUSTED", "EXPIRED"]
BENEFIT_PLAN_FIELD = {
    "LACTATION_CONSULT": "included_lactation_consults",
    "SLEEP_CONSULT": "included_sleep_consults",
}

# ---- 24/7 access & after-hours -----------------------------------------------
AFTER_HOURS_EVENING_START_MINUTE = 1080
AFTER_HOURS_MORNING_END_MINUTE = 480
AFTER_HOURS_SURCHARGE_CENTS = 7500
DECLARED_HOLIDAY_DATES = [
    "2026-05-25",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
]
WEEKEND_WEEKDAY_NAMES = ["SATURDAY", "SUNDAY"]
WEEKDAY_NAMES = [
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY",
]
AFTER_HOURS_REASONS = ["WEEKEND", "HOLIDAY", "WEEKDAY_EVENING", "WEEKDAY_EARLY_MORNING"]

# ---- telehealth --------------------------------------------------------------
TELEHEALTH_PROHIBITED_ENCOUNTER_TYPES = ["NEWBORN_WEIGHT_CHECK"]

# ---- scheduling geometry ------------------------------------------------------
CONSULT_TURNAROUND_BUFFER_MINUTES = 15
ENCOUNTER_DEFAULT_DURATION_MINUTES = 30
MAX_CONCURRENT_OPEN_ENCOUNTERS_PER_CHILD = 1
MAX_CONSULT_RESCHEDULES = 2

# ---- school / camp forms -------------------------------------------------------
FORM_WELL_VISIT_RECENCY_DAYS = 365
FORM_TYPES = ["SCHOOL", "CAMP", "SPORTS"]
FORM_STATUSES = ["PENDING", "BLOCKED", "ISSUED"]
FORM_BLOCKED_REASONS = [
    "MEMBERSHIP_NOT_ACTIVE",
    "IMMUNIZATION_INCOMPLETE",
    "WELL_VISIT_STALE",
]

# ---- service catalog -----------------------------------------------------------
ENCOUNTER_SERVICE_CODE_MAP = {
    "SICK_VISIT": "SICK_VISIT",
    "AFTER_HOURS_CONTACT": "SICK_VISIT",
    "ROUTINE_QUESTION": "TELEHEALTH_VISIT",
    "NEWBORN_WEIGHT_CHECK": "WELL_VISIT",
}
SERVICE_BILLED_AMOUNT_CENTS = {
    "WELL_VISIT": 22000,
    "SICK_VISIT": 18000,
    "TELEHEALTH_VISIT": 12000,
    "AFTER_HOURS_SURCHARGE": 7500,
}
MEMBERSHIP_COVERED_SERVICE_CODES = ["WELL_VISIT", "TELEHEALTH_VISIT"]
INSURANCE_ELIGIBLE_SERVICE_CODES = ["SICK_VISIT"]
SERVICE_CODES = [
    "WELL_VISIT",
    "SICK_VISIT",
    "TELEHEALTH_VISIT",
    "AFTER_HOURS_SURCHARGE",
    "LACTATION_CONSULT",
    "SLEEP_CONSULT",
]
ROUTE_VALUES = ["COVERED_BY_MEMBERSHIP", "BILLED_TO_INSURANCE", "PATIENT_RESPONSIBILITY"]
SERVICE_LINE_STATUSES = ["ROUTED", "ADJUDICATED", "SETTLED", "VOID"]

# ---- enums on other entities ---------------------------------------------------
PLAN_TIERS = ["ESSENTIAL", "PLUS", "PREMIER"]
POLICY_STATUSES = ["ACTIVE", "TERMINATED"]
MEMBERSHIP_STATUSES = ["PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "CANCELLED"]
MEMBERSHIP_OCCUPYING_STATUSES = ["PENDING_ACTIVATION", "ACTIVE", "SUSPENDED"]
BOOKING_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
COVERAGE_ROUTES = ["ENTITLEMENT", "OVERAGE"]
ENCOUNTER_TYPES = [
    "SICK_VISIT",
    "AFTER_HOURS_CONTACT",
    "ROUTINE_QUESTION",
    "NEWBORN_WEIGHT_CHECK",
]
MODALITIES = ["IN_PERSON", "TELEHEALTH"]
CLINICAL_STATUSES = ["SCHEDULED", "CLINICALLY_COMPLETE", "CANCELLED"]
BILLING_STATUSES = [
    "BILLING_PENDING",
    "BILLING_ROUTED",
    "BILLING_CLOSED",
    "BILLING_VOID",
]
