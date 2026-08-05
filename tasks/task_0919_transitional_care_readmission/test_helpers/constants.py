"""Domain thresholds and literal programme constants stated in the PRD."""

# The logical clock reads this instant before any caller has moved it.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# End-of-day suffix appended to a calendar date to obtain the instant it expires.
END_OF_DAY_SUFFIX = "T23:59:59.999Z"

# --- Intake gauntlet -------------------------------------------------------
ELIGIBLE_DISPOSITIONS = ["HOME", "HOME_HEALTH", "SNF_SHORT_TERM", "ASSISTED_LIVING"]
INELIGIBLE_DISPOSITIONS = ["HOSPICE", "LTACH", "EXPIRED", "AMA"]
INTAKE_WINDOW_DAYS = 2
OPEN_EPISODE_STATUSES = ["INTAKE", "ACTIVE", "SERVICE_PERIOD_CLOSED"]

# --- Risk scoring ----------------------------------------------------------
LOS_INPATIENT_POINTS_PER_DAY = 1.5
LOS_INPATIENT_POINT_CAP = 12
LOS_OBSERVATION_HOURS_PER_POINT = 12.0
LOS_OBSERVATION_POINT_CAP = 6
ACUITY_POINTS = {"ELECTIVE": 0, "URGENT": 6, "EMERGENT": 10}
COMORBIDITY_POINTS_PER_CONDITION = 2.5
COMORBIDITY_POINT_CAP = 20
UTILIZATION_POINTS_PER_ED_VISIT = 3
UTILIZATION_POINTS_PER_ADMISSION = 5
UTILIZATION_POINT_CAP = 24
SOCIAL_POINTS_PER_FLAG = 2.5
SOCIAL_POINT_CAP = 10
RISK_SCORE_CAP = 60
RISK_TIER_MODERATE_FLOOR = 18
RISK_TIER_HIGH_FLOOR = 32
RISK_TIER_SEVERE_FLOOR = 45

# --- Tier-driven programme parameters --------------------------------------
CONTACT_SLA_BUSINESS_DAYS = {
    "LOW": 2,
    "MODERATE": 2,
    "HIGH": 2,
    "SEVERE": 1,
}
REQUIRED_COMPLEXITY_BY_TIER = {
    "LOW": "MODERATE_COMPLEXITY",
    "MODERATE": "MODERATE_COMPLEXITY",
    "HIGH": "HIGH_COMPLEXITY",
    "SEVERE": "HIGH_COMPLEXITY",
}

# --- Interactive contact ladder --------------------------------------------
MAX_CONTACT_ATTEMPTS = 4
CONTACT_MODALITY_LADDER = ["PHONE", "PHONE", "SECURE_MESSAGE", "HOME_VISIT"]
CONTACT_ATTEMPT_COOLDOWN_MINUTES = 240
HOURS_PER_SLA_DAY_CALENDAR_VARIANT = 24

# --- Face-to-face visit ----------------------------------------------------
VISIT_DUE_DAYS_MODERATE_COMPLEXITY = 14
VISIT_DUE_DAYS_HIGH_COMPLEXITY = 7
VISIT_TURNAROUND_BUFFER_MINUTES = 20
MODERATE_REQUIRED_ELEMENTS = [
    "MED_REC_REVIEWED",
    "DISCHARGE_SUMMARY_REVIEWED",
    "PATIENT_EDUCATION",
]
HIGH_REQUIRED_ELEMENTS = [
    "MED_REC_REVIEWED",
    "DISCHARGE_SUMMARY_REVIEWED",
    "PATIENT_EDUCATION",
    "HIGH_COMPLEXITY_MDM",
    "COMMUNITY_SERVICE_REFERRAL",
]

# --- Medication reconciliation ---------------------------------------------
BLOCKING_DISCREPANCY_SEVERITIES = ["HIGH", "CRITICAL"]
DEFERRABLE_DISCREPANCY_SEVERITIES = ["LOW", "MODERATE"]

# --- Typed barriers --------------------------------------------------------
BARRIER_SLA_HOURS = {
    "TRANSPORTATION": 48,
    "INSURANCE_AUTH": 72,
    "LANGUAGE": 24,
    "CAREGIVER_AVAILABILITY": 96,
    "PHARMACY_ACCESS": 36,
}
BARRIER_BLOCKING_TYPES = ["TRANSPORTATION", "INSURANCE_AUTH", "PHARMACY_ACCESS"]
BARRIER_NONBLOCKING_TYPES = ["LANGUAGE", "CAREGIVER_AVAILABILITY"]
BARRIER_OWNER_ROLE = {
    "TRANSPORTATION": "CareNavigator",
    "INSURANCE_AUTH": "BillingSpecialist",
    "LANGUAGE": "CareNavigator",
    "CAREGIVER_AVAILABILITY": "CareNavigator",
    "PHARMACY_ACCESS": "Clinician",
}
BARRIER_ESCALATION_RED_FLAG_TIER = "TIER_2"

# --- Red-flag escalation ---------------------------------------------------
REDFLAG_ACK_SLA_MINUTES = {"TIER_1": 30, "TIER_2": 120, "TIER_3": 480}
REDFLAG_ROUTING_ROLE = {
    "TIER_1": "Clinician",
    "TIER_2": "CareNavigator",
    "TIER_3": "CareNavigator",
}
MAX_REDFLAG_PROMOTIONS = 2
CONTACT_REFUSED_RED_FLAG_TIER = "TIER_3"
VISIT_WINDOW_AT_RISK_RED_FLAG_TIER = "TIER_2"

# --- 30-day tracking / readmission -----------------------------------------
READMISSION_WINDOW_DAYS = 30
READMISSION_COUNTING_CLASSES = ["UNPLANNED_INPATIENT"]
READMISSION_EXCLUDED_CLASSES = [
    "PLANNED_INPATIENT",
    "OBSERVATION_ONLY",
    "ED_TREAT_AND_RELEASE",
]

# --- TCM billing -----------------------------------------------------------
SERVICE_PERIOD_DAYS = 30
TCM_MODERATE_CODE = "99495"
TCM_HIGH_CODE = "99496"
TCM_MODERATE_BASE_RATE_CENTS = 20450
TCM_HIGH_BASE_RATE_CENTS = 27680
WITHHOLD_TIER_THRESHOLD_CENTS = 20000
WITHHOLD_PCT_ABOVE_THRESHOLD = 0.03
WITHHOLD_PCT_BELOW_THRESHOLD = 0.01
MAX_CLAIM_APPEALS = 2
NON_TERMINAL_CLAIM_STATUSES = ["PREPARED", "SUBMITTED", "DENIED", "APPEALED"]
TERMINAL_CLAIM_STATUSES = ["PAID", "DENIED_FINAL", "VOIDED"]

# --- Handoff / workload ----------------------------------------------------
HANDOFF_RESPONSE_WINDOW_HOURS = 24
NAVIGATOR_DEFAULT_ACTIVE_EPISODE_CAP = 5
WORKLOAD_WEIGHT_BY_TIER = {"LOW": 1, "MODERATE": 1, "HIGH": 2, "SEVERE": 3}

# --- Global write gate -----------------------------------------------------
FROZEN_EPISODE_STATUSES = ["BILLED", "CLOSED_READMITTED", "ADMIN_CLOSED"]

# --- Canonical fixture inputs ----------------------------------------------
# Referral inputs that score 6 + 6 + 13 + 11 + 8 = 44 -> HIGH tier.
HIGH_TIER_REFERRAL_INPUTS = {
    "stay_type": "INPATIENT",
    "length_of_stay_days": 4,
    "admission_acuity": "URGENT",
    "comorbidity_count": 5,
    "prior_ed_visits_6mo": 2,
    "prior_admissions_6mo": 1,
    "social_risk_flags_count": 3,
}
# Referral inputs that score 3 + 6 + 5 + 17 + 0 = 31 -> MODERATE tier.
MODERATE_TIER_REFERRAL_INPUTS = {
    "stay_type": "INPATIENT",
    "length_of_stay_days": 2,
    "admission_acuity": "URGENT",
    "comorbidity_count": 2,
    "prior_ed_visits_6mo": 4,
    "prior_admissions_6mo": 1,
    "social_risk_flags_count": 0,
}
# Referral inputs that saturate every component -> risk_score 60 -> SEVERE tier.
SEVERE_TIER_REFERRAL_INPUTS = {
    "stay_type": "INPATIENT",
    "length_of_stay_days": 8,
    "admission_acuity": "EMERGENT",
    "comorbidity_count": 8,
    "prior_ed_visits_6mo": 4,
    "prior_admissions_6mo": 4,
    "social_risk_flags_count": 4,
}
