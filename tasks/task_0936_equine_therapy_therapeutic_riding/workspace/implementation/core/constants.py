"""Every declared constant from the scaffold / PRD.  No value is invented here."""

LOGICAL_CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

MINUTES_PER_HOUR = 60
SECONDS_PER_HOUR = 3600
HOURS_ROUNDING_DECIMALS = 2
WEIGHT_ROUNDING_DECIMALS = 2

RELEASE_VALIDITY_DAYS = 365
REASSESSMENT_INTERVAL_DAYS = 365
REASSESSMENT_DUE_WARNING_DAYS = 30

MAX_HORSE_LOAD_FRACTION = "0.20"
BACKRIDER_WEIGHT_LB = "140.0"
HORSE_MAX_SESSIONS_PER_DAY = 3
HORSE_MAX_MOUNTED_MINUTES_PER_DAY = 150
HORSE_MAX_MOUNTED_MINUTES_PER_WEEK = 240
HORSE_REST_INTERVAL_MINUTES = 15
HORSE_POST_INCIDENT_REST_DAYS = 3

SESSION_MIN_DURATION_MINUTES = 30
SESSION_MAX_DURATION_MINUTES = 90

QUALIFICATION_VALIDITY_DAYS = 365
VOLUNTEER_RETRAINING_INTERVAL_DAYS = 365
VOLUNTEER_SUSPENSION_DAYS_SEV_1 = 30

CERT_VALIDITY_DAYS = 730
CERT_GRACE_DAYS = 60
CERT_RENEWAL_CE_HOURS = 20

LATE_CANCELLATION_WINDOW_HOURS = 24
LATE_CANCELLATION_FEE_PCT = "0.50"
NO_SHOW_FEE_PCT = "1.00"

GOAL_MET_CONSECUTIVE_HITS = 2
GOAL_STALE_AFTER_DAYS = 90
GOAL_MIN_RATING = 1
GOAL_MAX_RATING = 5

SCHOLARSHIP_MAX_CAP_PCT = "0.90"
ASSESSMENT_MIN_SCORE = 0
ASSESSMENT_MAX_SCORE = 10

RIDER_MAX_WEIGHT_LB = 400

BASE_RATE_CENTS_PER_MINUTE = {
    "THERAPEUTIC_RIDING": 150,
    "HIPPOTHERAPY": 260,
    "EQUINE_LEARNING": 120,
    "VAULTING": 180,
}

SLIDING_SCALE_PCT = {
    "BAND_A": "0.60",
    "BAND_B": "0.40",
    "BAND_C": "0.20",
    "BAND_D": "0.00",
}

INSTRUCTOR_TIER_ORDINAL = {
    "IN_TRAINING": 0,
    "REGISTERED": 1,
    "ADVANCED": 2,
    "MASTER": 3,
}

INDEPENDENCE_CREW_MATRIX = {
    "LEVEL_1": {"required_sidewalker_count": 2, "requires_leader": True,
                "sidewalker_hold_type": "OVER_THE_THIGH"},
    "LEVEL_2": {"required_sidewalker_count": 2, "requires_leader": True,
                "sidewalker_hold_type": "THIGH_HOLD"},
    "LEVEL_3": {"required_sidewalker_count": 1, "requires_leader": True,
                "sidewalker_hold_type": "ARM_OVER_THIGH"},
    "LEVEL_4": {"required_sidewalker_count": 0, "requires_leader": False,
                "sidewalker_hold_type": "NO_CONTACT"},
}

CREW_ROLE_MIN_AGE = {"LEADER": 16, "SIDEWALKER": 14, "BARN": 12}
CREW_ROLE_MIN_TRAINING_HOURS = {"LEADER": 12, "SIDEWALKER": 6, "BARN": 3}

INCIDENT_SEVERITY_MATRIX = {
    ("FALL", True): "SEV_1",
    ("FALL", False): "SEV_2",
    ("MEDICAL_EVENT", True): "SEV_1",
    ("MEDICAL_EVENT", False): "SEV_1",
    ("LOOSE_HORSE", True): "SEV_1",
    ("LOOSE_HORSE", False): "SEV_2",
    ("EQUIPMENT_FAILURE", True): "SEV_2",
    ("EQUIPMENT_FAILURE", False): "SEV_3",
    ("NEAR_MISS", True): "SEV_3",
    ("NEAR_MISS", False): "SEV_3",
}

INCIDENT_REPORT_DEADLINE_HOURS = {"SEV_1": 24, "SEV_2": 48, "SEV_3": 72}

INCIDENT_HOLD_MATRIX = {
    "SEV_1": {"rider_medical_hold": True, "horse_rest_hold": True,
              "volunteer_suspension": True, "instructor_suspension": True},
    "SEV_2": {"rider_medical_hold": False, "horse_rest_hold": True,
              "volunteer_suspension": True, "instructor_suspension": False},
    "SEV_3": {"rider_medical_hold": False, "horse_rest_hold": False,
              "volunteer_suspension": False, "instructor_suspension": False},
}

FUNDING_SOURCES_BY_CHARGE_TYPE = {
    "SESSION_FEE": ["GRANT", "SCHOLARSHIP", "SLIDING_SCALE", "PAYER", "PRIVATE_PAY"],
    "LATE_CANCELLATION_FEE": ["SLIDING_SCALE", "PAYER", "PRIVATE_PAY"],
    "NO_SHOW_FEE": ["SLIDING_SCALE", "PAYER", "PRIVATE_PAY"],
}

SEQUENCE_INDEX_BY_SOURCE = {
    "GRANT": 1, "SCHOLARSHIP": 2, "SLIDING_SCALE": 3, "PAYER": 4, "PRIVATE_PAY": 5,
}

# Literal reason strings (§3.3, §3.6, §3.9)
HORSE_HOLD_REASON_INCIDENT = "INCIDENT_REST_HOLD"
HORSE_HOLD_REASON_MANUAL = "MANUAL"
CREW_RELEASE_REASON_CASCADE = "SESSION_CANCELLED"
VOLUNTEER_SUSPENSION_REASON_SEV_1 = "INCIDENT_SEV_1"
VOLUNTEER_SUSPENSION_REASON_SEV_2 = "INCIDENT_SEV_2"
OPEN_ENDED_SUSPENSION_INSTANT = "9999-12-31T00:00:00.000Z"

ROLES = ["ProgramAdmin", "Instructor", "VolunteerCoordinator",
         "IntakeCoordinator", "BillingClerk"]

PROGRAM_CODES = ["THERAPEUTIC_RIDING", "HIPPOTHERAPY", "EQUINE_LEARNING", "VAULTING"]
ACTIVITY_TYPES = PROGRAM_CODES
DEMOGRAPHIC_GROUPS = ["VETERAN", "YOUTH", "ADULT", "SENIOR"]
INCOME_BANDS = ["BAND_A", "BAND_B", "BAND_C", "BAND_D"]
FUNDING_MODES = ["PRIVATE_PAY_ALLOWED", "FUNDED_ONLY"]
ASSESSMENT_TYPES = ["INTAKE", "ANNUAL_REASSESSMENT"]
POLICY_TIERS = ["CONTRAINDICATION", "PRECAUTION", "CLEAR"]
CERT_LEVELS = ["IN_TRAINING", "REGISTERED", "ADVANCED", "MASTER"]
GOAL_DOMAINS = ["PHYSICAL", "COGNITIVE", "SOCIAL_EMOTIONAL", "BEHAVIORAL", "EDUCATIONAL"]
INCIDENT_TYPES = ["FALL", "LOOSE_HORSE", "NEAR_MISS", "EQUIPMENT_FAILURE", "MEDICAL_EVENT"]
CREW_ROLES_ASSIGNMENT = ["LEADER", "SIDEWALKER"]
CREW_ROLES_QUALIFICATION = ["LEADER", "SIDEWALKER", "BARN"]
HOLD_TYPES_MANUAL = ["VET_HOLD", "FARRIER_HOLD"]
HOLD_TYPES_CREW = ["NO_CONTACT", "ARM_OVER_THIGH", "THIGH_HOLD", "OVER_THE_THIGH", "ANKLE_HOLD"]
CANCELLATION_REASON_INPUT_MEMBERS = ["RIDER_REQUEST", "WEATHER", "HORSE_PULLED", "PROGRAM_CLOSURE"]

# §2.9 — the CLOSED 17-field enum routing list.  A request BODY field whose name
# appears here, carrying a value outside its declared member set, is the only
# thing that returns ERR_INVALID_ENUM.  No other field routes there.
ENUM_ERROR_FIELD_LIST = [
    "household_income_band", "demographic_group", "program_code", "funding_mode",
    "activity_type", "assessment_type", "tier", "min_instructor_tier",
    "certification_level", "crew_role", "hold_type", "incident_type",
    "cancellation_reason", "domain", "restricted_program_code",
    "restricted_demographic", "variant",
]
