"""Enum value sets and system-field expectations for the domain entities.

The four append-only record types listed in PRD section 2.9 carry only `id` and
`created_at`; every other entity additionally carries `updated_at` and
`version`. `APPEND_ONLY_ENTITIES` and `VERSIONED_ENTITIES` capture that split so
tests can state which system fields a row must and must not expose.
"""

# --- System-field families (PRD 2.9) -----------------------------------------

APPEND_ONLY_ENTITIES = [
    "TrainingRecord",
    "OperationalInspectionLog",
    "BlockAssignment",
    "WeatherObservation",
]

VERSIONED_ENTITIES = [
    "Course",
    "Element",
    "Facilitator",
    "ProfessionalInspection",
    "GroupClient",
    "Booking",
    "Participant",
    "ProgramBlock",
    "BelayEquipment",
    "Incident",
]

APPEND_ONLY_SYSTEM_FIELDS = ["id", "created_at"]
VERSIONED_SYSTEM_FIELDS = ["id", "created_at", "updated_at", "version"]

# --- Enumerations ------------------------------------------------------------

COURSE_POSTURES = ["OPEN", "RESTRICTED", "CLOSED"]
COURSE_POSTURE_REASONS = [
    "NONE",
    "LIGHTNING_STOP",
    "WIND_STOP",
    "COLD_STOP",
    "INSPECTION_OVERDUE",
    "RESCUE_READINESS",
    "SERIOUS_INCIDENT",
    "ELEMENT_RESTRICTED",
    "LIGHTNING_WATCH",
    "WIND_WATCH",
]

ELEMENT_STATUSES = ["SERVICEABLE", "RESTRICTED", "OUT_OF_SERVICE", "RETIRED"]
RETIREMENT_BASES_ELEMENT = ["CALENDAR", "USAGE"]
RETIREMENT_BASES_EQUIPMENT = ["MANUFACTURE", "SERVICE", "CYCLE"]

STAFF_TYPES = ["STAFF_FACILITATOR", "SAFETY_OFFICER", "CONTRACT_INSPECTOR"]
CERT_STATUSES = ["ACTIVE", "PROBATION", "LAPSED"]
TRAINING_KINDS = ["RESCUE_DRILL", "REFRESHER", "RECERTIFICATION"]

INSPECTION_STATUSES = [
    "DRAFT",
    "FILED_PASS",
    "FILED_CONDITIONAL",
    "FILED_FAIL",
    "DISPOSED",
]
INSPECTION_OUTCOMES = ["NONE", "PASS", "CONDITIONAL", "FAIL"]

OPERATIONAL_LOG_RESULTS = ["CLEAR", "DEFECT_MINOR", "DEFECT_MAJOR"]

EQUIPMENT_STATUSES = ["IN_SERVICE", "QUARANTINED", "RETIRED"]

BOOKING_STATUSES = [
    "DRAFT",
    "QUOTED",
    "CONFIRMED",
    "AT_RISK",
    "WEATHER_HOLD",
    "DELIVERED",
    "CANCELLED",
]
ROSTER_STATUSES = ["BLOCKED", "INCOMPLETE", "READY"]
CANCELLATION_VARIANTS = ["CLIENT_INITIATED", "OPERATOR_WEATHER_INITIATED"]

HEALTH_FORM_STATUSES = ["MISSING", "SUBMITTED", "FLAGGED", "CLEARED"]
SCREENING_STATUSES = ["BLOCKED", "CONDITIONAL", "ELIGIBLE"]

BLOCK_STATUSES = [
    "SCHEDULED",
    "BLOCKED_UNSAFE",
    "IN_PROGRESS",
    "COMPLETED",
    "ABANDONED",
]

INCIDENT_SEVERITIES = ["NEAR_MISS", "MINOR", "MODERATE", "SERIOUS"]
INCIDENT_STATUSES = ["REPORTED", "UNDER_REVIEW", "CLOSED_NO_ACTION", "CLOSED_CORRECTIVE"]
INCIDENT_DISPOSITIONS = ["NO_ACTION", "CORRECTIVE"]
CORRECTIVE_ACTIONS = ["NONE", "ELEMENT_RESTRICTED", "EQUIPMENT_QUARANTINED"]

WEATHER_POSTURE_REASONS = [
    "NONE",
    "LIGHTNING_STOP",
    "LIGHTNING_WATCH",
    "WIND_STOP",
    "WIND_WATCH",
    "COLD_STOP",
]
