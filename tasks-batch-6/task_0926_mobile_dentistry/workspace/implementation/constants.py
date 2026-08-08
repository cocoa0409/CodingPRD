"""Declared constants for the Mobile Dentistry API.

Every value here traces to a named constant in the PRD / scaffold.
"""

# ---- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# ---- roles -----------------------------------------------------------------
ROLES = [
    "ProgramAdmin",
    "SiteCoordinator",
    "FieldDentist",
    "FieldHygienist",
    "DentalAssistant",
    "BillingSpecialist",
    "Guardian",
]

# ---- pagination ------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---- consent ---------------------------------------------------------------
CONSENT_SNF_REAFFIRMATION_DAYS = 365

CONSENT_TIER_RANK = {
    "SCREENING_ONLY": 1,
    "SCREENING_FLUORIDE": 2,
    "SCREENING_FLUORIDE_SEALANT": 3,
    "FULL_WITH_RADIOGRAPHS": 4,
}

# ---- triage ----------------------------------------------------------------
SCHOOL_URGENT_LESION_THRESHOLD = 1
SNF_MEDICAL_COMPLEXITY_THRESHOLD = 3
SNF_ORAL_HYGIENE_POOR_THRESHOLD = 3

# ---- portable unit ---------------------------------------------------------
UNIT_CALIBRATION_VALID_DAYS = 180
UNIT_CALIBRATION_DUE_WARNING_DAYS = 30
UNIT_TRANSPORT_BUFFER_MINUTES = 90

# ---- sterilization ---------------------------------------------------------
SPORE_INCUBATION_HOURS = 24
SPORE_TAINT_LOOKBACK_DAYS = 14

# ---- procedures ------------------------------------------------------------
PROCEDURE_CODES = ["D0190", "D0150", "D1206", "D1351", "D0272"]

PROCEDURE_REQUIRED_TIER = {
    "D0190": "SCREENING_ONLY",
    "D0150": "SCREENING_ONLY",
    "D1206": "SCREENING_FLUORIDE",
    "D1351": "SCREENING_FLUORIDE_SEALANT",
    "D0272": "FULL_WITH_RADIOGRAPHS",
}

PROCEDURE_CHAIR_MINUTES = {
    "D0190": 10,
    "D0150": 15,
    "D1206": 8,
    "D1351": 12,
    "D0272": 10,
}

PROCEDURE_FEE_SCHEDULE_CENTS = {
    "D0190": 3475,
    "D0150": 5825,
    "D1206": 4525,
    "D1351": 6350,
    "D0272": 4150,
}

# ---- site visit ------------------------------------------------------------
CHAIR_UTILIZATION_CAP_PCT_NUM = 85      # 0.85 expressed as an exact ratio
CHAIR_UTILIZATION_CAP_PCT_DEN = 100
VISIT_RESCHEDULE_MAX_COUNT = 2
VISIT_RESCHEDULE_WINDOW_DAYS = 30
TELEDENTISTRY_REVIEW_WINDOW_HOURS = 72

# ---- sliding fee -----------------------------------------------------------
FPL_BASE_ANNUAL_CENTS = 1560000
FPL_PER_ADDITIONAL_PERSON_CENTS = 550000
SLIDING_FEE_BAND_A_MAX_FPL_PCT = "100.0"
SLIDING_FEE_BAND_B_MAX_FPL_PCT = "138.0"
SLIDING_FEE_BAND_C_MAX_FPL_PCT = "175.0"
SLIDING_FEE_BAND_D_MAX_FPL_PCT = "200.0"

SLIDING_FEE_DISCOUNT = {
    "A": "1.00",
    "B": "0.75",
    "C": "0.55",
    "D": "0.35",
    "E": "0.00",
}
SLIDING_FEE_NOMINAL_FEE_CENTS = 2500

# ---- encounter pricing -----------------------------------------------------
SUPPLY_SURCHARGE_TIER1_MAX_SUBTOTAL_CENTS = 5000
SUPPLY_SURCHARGE_TIER2_MAX_SUBTOTAL_CENTS = 15000
SUPPLY_SURCHARGE_TIER1_CENTS = 500
SUPPLY_SURCHARGE_TIER2_CENTS = 1200
SUPPLY_SURCHARGE_TIER3_CENTS = 2000

MEDICAID_ENCOUNTER_RATE_CENTS = 18500
COMMERCIAL_ALLOWED_SCHEDULE_CENTS = {
    "D0190": 2600,
    "D0150": 4300,
    "D1206": 3375,
    "D1351": 4725,
    "D0272": 3100,
}
COMMERCIAL_COINSURANCE_PCT = "0.20"

# ---- referral --------------------------------------------------------------
REFERRAL_MAX_ATTEMPTS = 3
REFERRAL_NO_RESPONSE_DAYS = 21
REFERRAL_SLA_SCHOOL_URGENT_BUSINESS_DAYS = 3
REFERRAL_SLA_SCHOOL_EARLY_BUSINESS_DAYS = 15
REFERRAL_SLA_SCHOOL_ROUTINE_BUSINESS_DAYS = 45
REFERRAL_SLA_SNF_URGENT_HOURS = 48
REFERRAL_SLA_SNF_EARLY_CALENDAR_DAYS = 10
REFERRAL_SLA_SNF_ROUTINE_CALENDAR_DAYS = 45

# ---- follow up -------------------------------------------------------------
FOLLOW_UP_URGENT_DAYS = 7
FOLLOW_UP_EARLY_DAYS = 30
FOLLOW_UP_ROUTINE_DAYS = 180
FOLLOW_UP_GRACE_DAYS = 14

# ---- varnish ---------------------------------------------------------------
VARNISH_MIN_INTERVAL_DAYS = 90
VARNISH_MAX_APPLICATIONS_PER_PERIOD = 2

# ---- sealants --------------------------------------------------------------
SEALANT_ELIGIBLE_TOOTH_NUMBERS = [2, 3, 14, 15, 18, 19, 30, 31]
SEALANT_ELIGIBLE_SURFACES = ["O", "B", "L"]

# ---- supervision -----------------------------------------------------------
SUPERVISION_RANK = {
    "DIRECT": 1,
    "INDIRECT": 2,
    "GENERAL": 3,
    "SELF": 4,
}

SUPERVISION_MATRIX = {
    "D0190": {
        "DENTIST": "SELF",
        "HYGIENIST": "GENERAL",
        "PUBLIC_HEALTH_HYGIENIST": "GENERAL",
        "DENTAL_ASSISTANT": "NOT_PERMITTED",
    },
    "D0150": {
        "DENTIST": "SELF",
        "HYGIENIST": "NOT_PERMITTED",
        "PUBLIC_HEALTH_HYGIENIST": "GENERAL",
        "DENTAL_ASSISTANT": "NOT_PERMITTED",
    },
    "D1206": {
        "DENTIST": "SELF",
        "HYGIENIST": "INDIRECT",
        "PUBLIC_HEALTH_HYGIENIST": "GENERAL",
        "DENTAL_ASSISTANT": "DIRECT",
    },
    "D1351": {
        "DENTIST": "SELF",
        "HYGIENIST": "INDIRECT",
        "PUBLIC_HEALTH_HYGIENIST": "GENERAL",
        "DENTAL_ASSISTANT": "NOT_PERMITTED",
    },
    "D0272": {
        "DENTIST": "SELF",
        "HYGIENIST": "DIRECT",
        "PUBLIC_HEALTH_HYGIENIST": "DIRECT",
        "DENTAL_ASSISTANT": "NOT_PERMITTED",
    },
}

# ---- enum value sets (rung 7 closed list, exactly 21 request fields) -------
ENUM_SITE_TYPE = ["SCHOOL", "SNF"]
ENUM_ROSTER_DISCLOSURE_LEVEL = ["SUMMARY_ONLY", "CLINICAL_DETAIL"]
ENUM_HOLD_TYPE = ["WEATHER_CLOSURE", "OUTBREAK_LOCKDOWN", "ADMINISTRATIVE"]
ENUM_PATIENT_TYPE = ["STUDENT", "RESIDENT"]
ENUM_CAPACITY_DETERMINATION = ["NOT_ASSESSED", "HAS_CAPACITY", "LACKS_CAPACITY"]
ENUM_CONSENT_REGIME = ["SCHOOL_GUARDIAN", "SNF_RESPONSIBLE_PARTY"]
ENUM_SCOPE_TIER = [
    "SCREENING_ONLY",
    "SCREENING_FLUORIDE",
    "SCREENING_FLUORIDE_SEALANT",
    "FULL_WITH_RADIOGRAPHS",
]
ENUM_RESPONSIBLE_PARTY_AUTHORITY = [
    "DURABLE_POA",
    "HEALTHCARE_PROXY",
    "COURT_GUARDIAN",
    "SELF",
]
ENUM_STAFF_ROLE = [
    "DENTIST",
    "HYGIENIST",
    "PUBLIC_HEALTH_HYGIENIST",
    "DENTAL_ASSISTANT",
]
ENUM_SUPERVISION_LEVEL = ["DIRECT", "INDIRECT", "GENERAL", "SELF"]
ENUM_CREDENTIAL_STATUS = ["ACTIVE", "LAPSED", "INACTIVE"]
ENUM_PAYER_TYPE = ["MEDICAID_MCO", "COMMERCIAL_FFS", "UNINSURED"]
ENUM_SURFACE = ["O", "B", "L", "M", "D"]
ENUM_EXAM_MODALITY = ["ONSITE", "TELEDENTISTRY"]
ENUM_ADJUDICATE_OUTCOME = ["PAID", "DENIED"]
ENUM_RESPONSE_OUTCOME = ["ACCEPTED", "DECLINED", "NO_RESPONSE", "COMPLETED"]
ENUM_PERIOD_TO_STATUS = ["REPORTING", "OPEN", "CLOSED"]
ENUM_REPORT_TYPE = ["PARENT", "FACILITY_ROSTER", "PROGRAM_PERIOD"]
ENUM_SPORE_RESULT = ["PASSED", "FAILED"]

# ---- period freeze gate ----------------------------------------------------
PERIOD_GATED_ENDPOINTS = [
    "POST /mobile-dentistry/site-visits",
    "POST /mobile-dentistry/site-visits/{id}/reschedule",
    "POST /mobile-dentistry/site-visits/{id}/start",
    "POST /mobile-dentistry/site-visits/{id}/complete",
    "POST /mobile-dentistry/site-visits/{id}/cancel",
    "POST /mobile-dentistry/encounters",
    "POST /mobile-dentistry/encounters/{id}/screen",
    "POST /mobile-dentistry/encounters/{id}/exam",
    "POST /mobile-dentistry/encounters/{id}/close",
    "POST /mobile-dentistry/encounters/{id}/price",
    "POST /mobile-dentistry/encounters/{id}/claim",
    "POST /mobile-dentistry/encounters/{id}/adjudicate",
    "POST /mobile-dentistry/procedures",
    "POST /mobile-dentistry/procedures/{id}/perform",
    "POST /mobile-dentistry/procedures/{id}/void",
    "POST /mobile-dentistry/treatment-plans",
    "POST /mobile-dentistry/treatment-plans/{id}/activate",
    "POST /mobile-dentistry/sterilization-loads",
    "POST /mobile-dentistry/sterilization-loads/{id}/spore-result",
]
