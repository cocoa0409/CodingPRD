"""Declared constants, fixed catalogues and enum member sets.

Every value here traces to SCAFFOLD.yaml `constants` / PRD prose. Nothing is
invented and nothing is seeded as entity data.
"""

from decimal import Decimal

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- intake completeness -----------------------------------------------------
INTAKE_SECTION_WEIGHTS = {
    "CHIEF_COMPLAINT_TIMELINE": 25,
    "SYSTEMS_REVIEW": 25,
    "DIET_LIFESTYLE": 15,
    "MEDICATIONS_SUPPLEMENTS": 25,
    "FAMILY_HISTORY": 10,
}
INTAKE_SUBMITTED_WEIGHT_DIVISOR = 2
INTAKE_SECTION_VALIDITY_DAYS = 180
INTAKE_BOOKING_MIN_SCORE = 60
INTAKE_PROTOCOL_MIN_SCORE = 85

# --- membership tiers (fixed catalogue; no plan entity) ----------------------
MEMBERSHIP_CYCLE_DAYS = 30
MEMBERSHIP_TIERS = {
    "FOUNDATION": {
        "monthly_fee_cents": 9900,
        "included_visits": 2,
        "included_lab_credits": 1,
        "dispensary_discount_pct": Decimal("0.05"),
        "includes_messaging": False,
    },
    "CORE": {
        "monthly_fee_cents": 19900,
        "included_visits": 4,
        "included_lab_credits": 2,
        "dispensary_discount_pct": Decimal("0.10"),
        "includes_messaging": True,
    },
    "PREMIER": {
        "monthly_fee_cents": 34900,
        "included_visits": 8,
        "included_lab_credits": 4,
        "dispensary_discount_pct": Decimal("0.20"),
        "includes_messaging": True,
    },
}

# --- visits ------------------------------------------------------------------
VISIT_FEE_IN_PERSON_CENTS = 22500
VISIT_FEE_TELEHEALTH_CENTS = 18000
EXTENDED_VISIT_THRESHOLD_MINUTES = 45
EXTENDED_VISIT_BLOCK_MINUTES = 15
EXTENDED_VISIT_BLOCK_FEE_CENTS = 4500
TELEHEALTH_TURNAROUND_BUFFER_MINUTES = 10
ENCOUNTER_CANCEL_REFUND_WINDOW_HOURS = 24
LATE_CANCEL_NO_SHOW_FEE_CENTS = 7500

# --- messaging / e-visit -----------------------------------------------------
MESSAGE_SLA_HOURS = 48
EVISIT_PATIENT_MESSAGE_THRESHOLD = 4
EVISIT_CLINICAL_MINUTES_THRESHOLD = 15
EVISIT_FEE_CENTS = 9500

# --- functional lab panel catalogue (fixed; panel_code is the enum) ----------
LAB_PANELS = {
    "SERUM_METABOLIC": {
        "specimen_type": "SERUM",
        "fasting_required": True,
        "cycle_day_window_start": None,
        "cycle_day_window_end": None,
        "washout_class": None,
        "washout_days": 0,
        "cash_price_cents": 24000,
        "lab_credit_cost": 1,
    },
    "DUTCH_HORMONE": {
        "specimen_type": "DRIED_URINE",
        "fasting_required": False,
        "cycle_day_window_start": 19,
        "cycle_day_window_end": 22,
        "washout_class": "HORMONE_SUPPORT",
        "washout_days": 14,
        "cash_price_cents": 39000,
        "lab_credit_cost": 2,
    },
    "SALIVA_CORTISOL": {
        "specimen_type": "SALIVA",
        "fasting_required": False,
        "cycle_day_window_start": None,
        "cycle_day_window_end": None,
        "washout_class": "ADAPTOGEN",
        "washout_days": 7,
        "cash_price_cents": 21000,
        "lab_credit_cost": 1,
    },
    "STOOL_GI_MAP": {
        "specimen_type": "STOOL",
        "fasting_required": False,
        "cycle_day_window_start": None,
        "cycle_day_window_end": None,
        "washout_class": "PROBIOTIC",
        "washout_days": 10,
        "cash_price_cents": 45000,
        "lab_credit_cost": 2,
    },
}

# --- referral ----------------------------------------------------------------
RED_FLAG_REFERRAL_DUE_DAYS = 3
REFERRAL_MAX_ATTEMPTS = 3

# --- dispensary --------------------------------------------------------------
REVERSAL_AUTHORIZATION_THRESHOLD_CENTS = 20000
ADVERSE_REVERSAL_WINDOW_DAYS = 14

# --- titration ---------------------------------------------------------------
SYMPTOM_SCALE_MAX = 40
TITRATION_ADVANCE_DELTA_MIN = 8
TITRATION_HOLD_DELTA_MIN = 3
TITRATION_REDUCE_DELTA_MIN = 0
TITRATION_DOSE_ADVANCE_MULTIPLIER = Decimal("1.25")
TITRATION_DOSE_REDUCE_MULTIPLIER = Decimal("0.50")

# --- superbill ---------------------------------------------------------------
SUPERBILL_MAX_REVISIONS = 3

# --- pagination --------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- roles -------------------------------------------------------------------
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_ND = "NaturopathicDoctor"
ROLE_HEALTH_COACH = "HealthCoach"
ROLE_DISPENSARY_TECH = "DispensaryTech"
ROLE_CLINICAL_DIRECTOR = "ClinicalDirector"
ROLE_BILLING = "BillingSpecialist"
ROLE_PATIENT = "Patient"

ALL_ROLES = [
    ROLE_PRACTICE_ADMIN,
    ROLE_ND,
    ROLE_HEALTH_COACH,
    ROLE_DISPENSARY_TECH,
    ROLE_CLINICAL_DIRECTOR,
    ROLE_BILLING,
    ROLE_PATIENT,
]

# --- enum member sets --------------------------------------------------------
CREDENTIALS = ["ND", "HEALTH_COACH", "DISPENSARY_TECH", "CLINICAL_DIRECTOR"]
SECTION_TYPES = list(INTAKE_SECTION_WEIGHTS.keys())
INTAKE_STATUSES = ["SUBMITTED", "ATTESTED", "EXPIRED"]
TIERS = list(MEMBERSHIP_TIERS.keys())
MEMBERSHIP_STATUSES = ["ACTIVE", "PAUSED", "EXPIRED"]
PANEL_CODES = list(LAB_PANELS.keys())
FUNDING_SOURCES = ["MEMBERSHIP_CREDIT", "CASH"]
LAB_ORDER_STATUSES = [
    "ORDERED",
    "WASHOUT_HOLD",
    "COLLECTED",
    "RESULTED",
    "CRITICAL_ESCALATED",
    "INTERPRETED",
    "CANCELLED",
]
PROTOCOL_STATUSES = [
    "DRAFT",
    "ISSUED",
    "ACTIVE",
    "COMPLETED",
    "SUPERSEDED",
    "DISCONTINUED",
]
PROTOCOL_ITEM_STATUSES = ["ACTIVE", "HELD", "DISCONTINUED", "COMPLETED"]
SUPPLEMENT_CLASSES = [
    "HORMONE_SUPPORT",
    "ADAPTOGEN",
    "PROBIOTIC",
    "BOTANICAL",
    "VITAMIN_MINERAL",
    "ENZYME",
]
INTERACTION_SEVERITIES = ["NONE", "MODERATE", "SEVERE"]
DISPENSE_STATUSES = ["DISPENSED", "REVERSED"]
MODALITIES = ["IN_PERSON", "TELEHEALTH", "EVISIT"]
SCHEDULING_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]
BILLING_STATUSES = [
    "CASH_PENDING",
    "ENTITLEMENT_RESERVED",
    "ENTITLEMENT_CONSUMED",
    "CASH_CHARGED",
    "SUPERBILLED",
    "REFUNDED",
    "FORFEITED",
]
THREAD_STATUSES = ["OPEN", "ANSWERED", "CONVERTED_TO_EVISIT", "CLOSED"]
SUPERBILL_STATUSES = ["DRAFT", "ISSUED", "VOIDED", "DENIED", "APPEALED", "CLOSED"]
REFERRAL_STATUSES = [
    "SENT",
    "ACKNOWLEDGED",
    "REPORT_RECEIVED",
    "CLOSED",
    "DECLINED",
    "ABANDONED",
]
REFERRAL_TYPES = ["ROUTINE", "RED_FLAG_AUTO"]
CLINICAL_STATUSES = ["INTAKE", "ESTABLISHED", "INACTIVE"]
SCOPE_REVIEW_STATUSES = ["NONE", "UNDER_REVIEW", "CLEARED", "RESTRICTED"]
CLINICAL_WRITE_GATES = ["OPEN", "FROZEN_SCOPE_REVIEW", "FROZEN_RED_FLAG"]
PRICING_VARIANTS = ["RETAIL", "MEMBER", "PRACTITIONER_COST"]

# request-only enums
SCOPE_REVIEW_CLOSE_OUTCOMES = ["CLEARED", "RESTRICTED"]
SUPERBILL_ACTIONS = ["ISSUE", "VOID", "REISSUE", "REPORT_DENIAL", "APPEAL", "CLOSE"]
REFERRAL_ACTIONS = ["ACKNOWLEDGE", "REPORT", "CLOSE", "DECLINE", "RE_REFER"]
ADVERSE_REACTION_SEVERITIES = ["MILD", "MODERATE", "SEVERE"]

# system-recorded discontinue reasons
REASON_ADVERSE_REACTION = "ADVERSE_REACTION"
REASON_SUPERSEDED_BY_REVISION = "SUPERSEDED_BY_REVISION"
REASON_PROTOCOL_DISCONTINUED = "PROTOCOL_DISCONTINUED"

TITRATION_DECISIONS = ["ADVANCE", "HOLD", "REDUCE", "DISCONTINUE"]
