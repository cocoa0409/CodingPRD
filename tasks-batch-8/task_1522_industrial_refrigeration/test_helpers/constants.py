"""Domain thresholds and constants named in the PRD.

Sources: the charge ledger and posture rules (PRD sections 2.6-2.7), the
inspection interval rules (3.3), the floating head pressure formula and
ammonia saturation table (3.4), the training/drill rules (3.5), the leak
notification rule (3.8), and the checkpoint semantics (2.5).
"""

THRESHOLDS = {
    # Charge / threshold applicability
    "DEFAULT_THRESHOLD_LBS": 10000.0,
    "CHARGE_ROUNDING_STEP_LBS": 0.1,
    "THRESHOLD_AUDIT_DUE_DAYS": 1095,
    # Compliance posture weights and bands
    "W_OVERDUE_INSPECTION": 5,
    "W_OPEN_INCIDENT": 3,
    "W_EXPIRED_TRAINING": 2,
    "NONCOMPLIANT_FLOOR": 10,
    "DEGRADED_MAX_SCORE": 9,
    # Inspection scheduling
    "CONDITION_EXTENSION_FACTOR": 1.5,
    "MAX_INSPECTION_INTERVAL_DAYS": 1095,
    "FAIL_RECHECK_DAYS": 30,
    "DUE_SOON_WINDOW_DAYS": 30,
    # Training currency
    "TRAINING_VALIDITY_DAYS": 1095,
    "EXPIRING_SOON_DAYS": 90,
    # Drills
    "DRILL_QUIET_GAP_HOURS": 24,
    "DRILL_MIN_TRAINED_ATTENDEES": 2,
    # Leak notification
    "RQ_LBS": 100.0,
    "NOTIFY_WINDOW_MINUTES": 15,
    # Contractors
    "SAFETY_SCORE_MIN": 0,
    "SAFETY_SCORE_MAX": 100,
}

# Ammonia saturation pressure table (psig) keyed by temperature (F),
# as enumerated in the head-pressure workflow.
AMMONIA_SAT_PSIG_TABLE = {
    50: 74.5,
    60: 92.9,
    70: 114.1,
    80: 138.8,
    90: 166.4,
    100: 196.6,
}

# Load-band derates applied to the condenser approach temperature.
LOAD_DERATE_HIGH = 5.0    # load >= 90
LOAD_DERATE_MEDIUM = 2.5  # 75 <= load < 90
LOAD_DERATE_LOW = 0.0     # load < 75

TEST_DEFAULTS = {
    "FACILITY_NAME": "ColdCo Plant",
    "SYSTEM_NAME": "ER1",
    "DESIGN_CHARGE_LBS": 3000.0,
    "CONDENSER_APPROACH_F": 15.0,
    "MIN_HEAD_PSIG": 150.0,
    "MAX_HEAD_PSIG": 185.0,
    "OPERATOR_NAME": "Olivia Operator",
    "REPORTER_NAME": "Rita Reporter",
    "INVESTIGATOR_NAME": "Ivan Investigator",
    "ASSIGNEE_NAME": "Andy Assignee",
    "CONTRACTOR_NAME": "WeldPros Inc",
    "SAFETY_SCORE": 80,
    "QUALIFIED_UNTIL": "2027-06-01T00:00:00Z",
    "PERMIT_VALID_FROM": "2026-09-01T08:00:00Z",
    "PERMIT_VALID_UNTIL": "2026-09-01T12:00:00Z",
}

# Logical clock startup value (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
