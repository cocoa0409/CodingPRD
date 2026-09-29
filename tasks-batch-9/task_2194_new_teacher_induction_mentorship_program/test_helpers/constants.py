"""Business constants declared by the induction mentorship PRD.

Only values the PRD states literally are recorded here: enum member sets,
default values, thresholds, rate tables and the logical clock's starting
instant.  Nothing here is inferred.
"""

# --- Logical clock -------------------------------------------------------
# "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`"
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

# --- Roles ---------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_SITE_INDUCTION_LEAD = "SiteInductionLead"
ROLE_MENTOR = "Mentor"
ROLE_NOVICE_TEACHER = "NoviceTeacher"
ROLE_STATE_OFFICER = "StateCredentialingOfficer"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_SITE_INDUCTION_LEAD,
    ROLE_MENTOR,
    ROLE_NOVICE_TEACHER,
    ROLE_STATE_OFFICER,
]

# Roles whose X-User-ID is the id of a persisted row.
ENTITY_BACKED_ROLES = [
    ROLE_SITE_INDUCTION_LEAD,
    ROLE_MENTOR,
    ROLE_NOVICE_TEACHER,
]

# --- Enumerations --------------------------------------------------------
REGION_CODES = ["NORTH", "SOUTH", "EAST", "WEST"]

SUBJECT_AREAS = [
    "MATH",
    "SCIENCE",
    "ELA",
    "SOCIAL_STUDIES",
    "SPED",
    "WORLD_LANGUAGE",
    "CTE",
]

TRAINING_MODULE_CODES = [
    "FOUNDATIONS",
    "OBSERVATION_PROTOCOL",
    "EQUITY",
    "RECERT_REFRESH",
]

CONTACT_TYPES = ["ONE_ON_ONE", "CO_PLANNING", "MODEL_LESSON", "DEBRIEF"]

GROWTH_AREA_CODES = ["PLANNING", "INSTRUCTION", "ENVIRONMENT", "ASSESSMENT", "EQUITY"]

RUBRIC_KEYS = ["planning", "instruction", "environment", "assessment"]

ATTENDANCE_STATUSES = ["PRESENT", "LATE", "ABSENT", "EXCUSED"]

LICENSE_STAGES = ["PRELIMINARY", "PROVISIONAL", "CLEAR"]

RETENTION_OUTCOMES = [
    "RETAINED_SAME_SITE",
    "RETAINED_DISTRICT",
    "LEFT_DISTRICT",
    "LEFT_PROFESSION",
]

SUBJECT_ADJACENCY = {
    "MATH": ["SCIENCE", "CTE"],
    "SCIENCE": ["MATH", "CTE"],
    "ELA": ["SOCIAL_STUDIES", "WORLD_LANGUAGE"],
    "SOCIAL_STUDIES": ["ELA", "WORLD_LANGUAGE"],
    "SPED": ["ELA", "MATH"],
    "WORLD_LANGUAGE": ["ELA", "SOCIAL_STUDIES"],
    "CTE": ["MATH", "SCIENCE"],
}

# --- Defaults the PRD names ---------------------------------------------
DEFAULT_MENTOR_SLOT_CAP = 6
DEFAULT_SEMINAR_SESSIONS_REQUIRED = 6
DEFAULT_CASELOAD_CAP = 2
DEFAULT_ADJUSTMENT_CENTS = 0
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0

# --- Numeric bounds -----------------------------------------------------
MIN_LIMIT = 1
MAX_LIMIT = 100

MIN_CONTACT_MINUTES = 1
MAX_CONTACT_MINUTES = 300
MIN_DESCRIPTION_CHARS = 20
MAX_DESCRIPTION_CHARS = 1000
MIN_NARRATIVE_CHARS = 120
MAX_NARRATIVE_CHARS = 4000
MIN_GROWTH_AREAS = 1
MAX_GROWTH_AREAS = 4
MIN_RUBRIC_VALUE = 1
MAX_RUBRIC_VALUE = 4
MIN_CASELOAD_CAP = 1
MAX_CASELOAD_CAP = 4
MIN_MENTOR_SLOT_CAP = 1
MAX_MENTOR_SLOT_CAP = 40
MIN_SESSION_INDEX = 1
MAX_SESSION_INDEX = 24
MIN_CYCLE_INDEX = 1
MAX_CYCLE_INDEX = 8
MIN_MINUTES_ATTENDED = 0
MAX_MINUTES_ATTENDED = 480
MAX_ADJUSTMENT_CENTS_MAGNITUDE = 500000

# --- Certification ------------------------------------------------------
CERTIFY_REQUIRED_HOURS = 18.00
CERTIFY_REQUIRED_MODULES = ["FOUNDATIONS", "OBSERVATION_PROTOCOL", "EQUITY"]
RECERTIFY_REQUIRED_HOURS = 6.00
RECERTIFY_REQUIRED_MODULES = ["RECERT_REFRESH"]
CERTIFICATION_TERM_DAYS = 365

# --- Contact credit -----------------------------------------------------
CONTACT_TYPE_WEIGHTS = {
    "ONE_ON_ONE": 1.00,
    "CO_PLANNING": 1.00,
    "MODEL_LESSON": 1.25,
    "DEBRIEF": 0.75,
}
DAILY_CREDIT_CAP_MINUTES = 180

# --- Stipend rates ------------------------------------------------------
TIER_RATE_CENTS_PER_HOUR = {"EXACT": 4200, "ADJACENT": 3600, "CROSS": 2800}
CERT_MULTIPLIER_CERTIFIED = 1.00
CERT_MULTIPLIER_OTHERWISE = 0.50

# --- Seminar scheduling -------------------------------------------------
OBSERVATION_BUFFER_MINUTES = 30
MIN_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 240
WEEKLY_SEMINAR_CAP_MINUTES = 240
SEMINAR_CREDIT_RATIO_THRESHOLD = 0.75
LATE_PENALTY_MINUTES = 10

# --- Readiness ----------------------------------------------------------
CONTACT_MINUTE_TARGET = 600
OBSERVATION_CYCLE_TARGET = 2
READINESS_WEIGHT_CONTACT = 0.45
READINESS_WEIGHT_OBSERVATION = 0.30
READINESS_WEIGHT_SEMINAR = 0.25
READINESS_ELIGIBILITY_GATE = 85.00

# --- Completion scoring -------------------------------------------------
MILESTONE_COMPONENT_TARGET = 3
BASE_SCORE_WEIGHT_READINESS = 0.60
BASE_SCORE_WEIGHT_MILESTONE = 0.40
BONUS_HIGH_THRESHOLD = 90.00
BONUS_HIGH_VALUE = 5.00
BONUS_MID_THRESHOLD = 75.00
BONUS_MID_VALUE = 2.50
COMPLETION_SCORE_CEILING = 100.00
SUBMISSION_MIN_MILESTONES = 3
SUBMISSION_MIN_BASE_SCORE = 75.00

# --- Revision-loop bounds -----------------------------------------------
MAX_RESUBMITS = 2
MAX_FEEDBACK_RETURNS = 3
MAX_REVOCATIONS = 3
MAX_PACKET_REOPENINGS = 2
