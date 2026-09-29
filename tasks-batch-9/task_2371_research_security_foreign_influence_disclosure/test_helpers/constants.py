"""Domain thresholds and weights taken from the PRD's published calculations."""

# --------------------------------------------------------------------------- #
# Ownership and designation
# --------------------------------------------------------------------------- #
CONTROL_THRESHOLD_PCT = 50
MAX_OWNERSHIP_DEPTH = 8

DESIGNATION_STRICTNESS = {
    "NONE": 0,
    "UNVERIFIED_END_USER": 1,
    "ENTITY_LIST": 2,
    "FOREIGN_MILITARY": 3,
    "MALIGN_TALENT_PROGRAM": 4,
    "SDN": 5,
}

# --------------------------------------------------------------------------- #
# Subaward screening
# --------------------------------------------------------------------------- #
BLOCK_STRICTNESS = 2
BLOCK_BASE_POINTS = 40
STRICTNESS_POINT_STEP = 10
FLAG_POINTS = 20

# --------------------------------------------------------------------------- #
# Support statement reconciliation
# --------------------------------------------------------------------------- #
OUTSIDE_HOURS_PER_PERSON_MONTH = 160
MATERIAL_VARIANCE_PM = 1.00
MINOR_VARIANCE_PM = 0.25

# --------------------------------------------------------------------------- #
# Investigator risk score
# --------------------------------------------------------------------------- #
ITEM_POINTS = {
    "FOREIGN_APPOINTMENT": 12,
    "TALENT_PROGRAM": 30,
    "OUTSIDE_SUPPORT": 8,
    "IN_KIND_RESOURCE": 6,
    "VISITING_SCHOLAR": 10,
}
DESIGNATION_MULTIPLIER = {
    "NONE": 1.0,
    "UNVERIFIED_END_USER": 1.5,
    "ENTITY_LIST": 2.0,
    "FOREIGN_MILITARY": 2.5,
    "MALIGN_TALENT_PROGRAM": 3.0,
    "SDN": 3.0,
}
INCIDENT_POINTS = {"LOW": 5, "MODERATE": 12, "HIGH": 25, "CRITICAL": 40}
PAID_SURCHARGE = 5
ITEM_POINT_CAP = 60
DISCREPANCY_POINTS = 15
PLAN_CREDIT = 20
SCORE_MIN = 0
SCORE_MAX = 100

# --------------------------------------------------------------------------- #
# Commitment totals
# --------------------------------------------------------------------------- #
MONTHS_PER_YEAR = 12
ANNUAL_HOURS_BASE = 2080
FULL_COMMITMENT_PCT = 100

# --------------------------------------------------------------------------- #
# Disclosure completeness
# --------------------------------------------------------------------------- #
BASE_SCORE = 100
UNDISCLOSED_PENALTY = 25
LATE_ITEM_PENALTY = 8
REVISION_PENALTY = 6
TIER_A_FLOOR = 90
TIER_B_FLOOR = 70
MIN_CERTIFY_SCORE = 60
TIER_PENALTY = {"A": 0, "B": 5, "C": 12}

# --------------------------------------------------------------------------- #
# Disclosure posture
# --------------------------------------------------------------------------- #
RESTRICT_SCORE = 60
REVIEW_SCORE = 30

# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Project activation
# --------------------------------------------------------------------------- #
BLOCKER_ORDER = [
    "SECURITY_NOT_CLEARED",
    "DISCLOSURE_NOT_CERTIFIED",
    "TRAINING_INCOMPLETE",
    "SUBAWARD_BLOCKED",
    "SUPPORT_INCONSISTENT",
    "PERSONNEL_MISSING_PI",
    "INVESTIGATOR_SUSPENDED",
]

# --------------------------------------------------------------------------- #
# Travel device requirement
# --------------------------------------------------------------------------- #
HIGH_RISK_COUNTRIES = ["CN", "RU", "IR", "KP"]
HOST_STRICTNESS_FLOOR = 2

# --------------------------------------------------------------------------- #
# Incident severity and notification deadline
# --------------------------------------------------------------------------- #
TYPE_POINTS = {
    "UNDISCLOSED_APPOINTMENT": 20,
    "UNDISCLOSED_TALENT_PROGRAM": 40,
    "UNREPORTED_TRAVEL": 15,
    "RESTRICTED_ENTITY_COLLABORATION": 35,
    "DEVICE_COMPROMISE": 30,
}
NOTIFICATION_DAYS = {"LOW": 60, "MODERATE": 30, "HIGH": 10, "CRITICAL": 5}
ACTIVE_AWARD_SURCHARGE = 15
RESTRICTED_PROJECT_SURCHARGE = 10
PRIOR_INCIDENT_SURCHARGE = 10
PRIOR_INCIDENT_CAP = 20
MODERATE_FLOOR = 20
HIGH_FLOOR = 40
CRITICAL_FLOOR = 60

# --------------------------------------------------------------------------- #
# Controlled-area capacity and travel overlap
# --------------------------------------------------------------------------- #
OCCUPYING_STATUSES = ["REQUESTED", "ACTIVE", "SUSPENDED"]
TRAVEL_BLOCKING_STATUSES = ["SUBMITTED", "APPROVED"]

# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
