"""Domain thresholds and rates stated in the PRD narrative.

Every value here is quoted from PRD prose (never inferred), so tests can name
the threshold they exercise instead of repeating a magic number.
"""

# PRD 2.5 - "Before the clock has ever been set it reads exactly 2026-05-01T00:00:00Z."
LOGICAL_CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# PRD 2.6 - minutes become hours by dividing by 60 and rounding to 2 decimals.
MINUTES_PER_HOUR = 60
HOURS_ROUNDING_DECIMALS = 2
WEIGHT_ROUNDING_DECIMALS = 2

# PRD 3.2 - "The server computes expires_at as 365 days after signed_on".
RELEASE_VALIDITY_DAYS = 365
# PRD 3.1 - next_due_at is 365 days after performed_on; DUE window is the final 30 days.
REASSESSMENT_INTERVAL_DAYS = 365
REASSESSMENT_DUE_WARNING_DAYS = 30

# PRD 3.3 - max_load_lb is one fifth of body weight; a backrider adds 140.0 lb.
MAX_HORSE_LOAD_FRACTION = 0.20
BACKRIDER_WEIGHT_LB = 140.0

# PRD 3.3 - capacity ceilings and the rest buffer.
HORSE_MAX_SESSIONS_PER_DAY = 3
HORSE_MAX_MOUNTED_MINUTES_PER_DAY = 150
HORSE_MAX_MOUNTED_MINUTES_PER_WEEK = 240
HORSE_REST_INTERVAL_MINUTES = 15
# PRD 3.3 / 3.9 - an incident rest hold releases three days after occurred_at.
HORSE_POST_INCIDENT_REST_DAYS = 3

# PRD 3.6 - "a duration_minutes between 30 and 90 inclusive".
SESSION_MIN_DURATION_MINUTES = 30
SESSION_MAX_DURATION_MINUTES = 90

# PRD 3.4 - minimum ages and training hours per crew role.
CREW_ROLE_MIN_AGE = {"LEADER": 16, "SIDEWALKER": 14, "BARN": 12}
CREW_ROLE_MIN_TRAINING_HOURS = {"LEADER": 12, "SIDEWALKER": 6, "BARN": 3}
QUALIFICATION_VALIDITY_DAYS = 365
VOLUNTEER_RETRAINING_INTERVAL_DAYS = 365
# PRD 3.9 - a SEV_1 volunteer suspension lasts 30 days from occurred_at.
VOLUNTEER_SUSPENSION_DAYS_SEV_1 = 30
OPEN_ENDED_SUSPENSION_INSTANT = "9999-12-31T00:00:00.000Z"

# PRD 3.5 - renewal recomputes certification_expires_at 730 days after renewed_on.
CERT_VALIDITY_DAYS = 730
CERT_GRACE_DAYS = 60
CERT_RENEWAL_CE_HOURS = 20

# PRD 3.6 - the notice window and the two derived fee percentages.
LATE_CANCELLATION_WINDOW_HOURS = 24
LATE_CANCELLATION_FEE_PCT = 0.50
NO_SHOW_FEE_PCT = 1.00

# PRD 3.7 - two consecutive target hits meet a goal; 90 days of silence make it stale.
GOAL_MET_CONSECUTIVE_HITS = 2
GOAL_STALE_AFTER_DAYS = 90
GOAL_MIN_RATING = 1
GOAL_MAX_RATING = 5

# PRD 3.8 / 2.7 - scholarship cap ceiling and the assessment score range.
SCHOLARSHIP_MAX_CAP_PCT = 0.90
ASSESSMENT_MIN_SCORE = 0
ASSESSMENT_MAX_SCORE = 10

# PRD 3.6 - per-minute rates by activity_type, in whole cents.
BASE_RATE_CENTS_PER_MINUTE = {
    "THERAPEUTIC_RIDING": 150,
    "HIPPOTHERAPY": 260,
    "EQUINE_LEARNING": 120,
    "VAULTING": 180,
}

# PRD 3.8 step 3 - the sliding-scale discount per household income band.
SLIDING_SCALE_PCT = {"BAND_A": 0.60, "BAND_B": 0.40, "BAND_C": 0.20, "BAND_D": 0.00}

# PRD 3.2 - "IN_TRAINING is 0, REGISTERED is 1, ADVANCED is 2 and MASTER is 3".
INSTRUCTOR_TIER_ORDINAL = {
    "IN_TRAINING": 0,
    "REGISTERED": 1,
    "ADVANCED": 2,
    "MASTER": 3,
}

# PRD 3.1 - the independence ladder and the crew matrix it fixes.
INDEPENDENCE_CREW_MATRIX = {
    "LEVEL_1": {
        "required_sidewalker_count": 2,
        "requires_leader": True,
        "sidewalker_hold_type": "OVER_THE_THIGH",
    },
    "LEVEL_2": {
        "required_sidewalker_count": 2,
        "requires_leader": True,
        "sidewalker_hold_type": "THIGH_HOLD",
    },
    "LEVEL_3": {
        "required_sidewalker_count": 1,
        "requires_leader": True,
        "sidewalker_hold_type": "ARM_OVER_THIGH",
    },
    "LEVEL_4": {
        "required_sidewalker_count": 0,
        "requires_leader": False,
        "sidewalker_hold_type": "NO_CONTACT",
    },
}

# PRD 3.9 - reporting deadline in hours per severity.
INCIDENT_REPORT_DEADLINE_HOURS = {"SEV_1": 24, "SEV_2": 48, "SEV_3": 72}

# PRD 3.8 - the pinned waterfall order.
FUNDING_WATERFALL_SEQUENCE_INDEX = {
    "GRANT": 1,
    "SCHOLARSHIP": 2,
    "SLIDING_SCALE": 3,
    "PAYER": 4,
    "PRIVATE_PAY": 5,
}

# PRD 3.3 / 3.4 / 3.9 - literal strings the server writes verbatim.
HORSE_HOLD_REASON_INCIDENT = "INCIDENT_REST_HOLD"
HORSE_HOLD_REASON_MANUAL = "MANUAL"
CREW_RELEASE_REASON_CASCADE = "SESSION_CANCELLED"
VOLUNTEER_SUSPENSION_REASON_SEV_1 = "INCIDENT_SEV_1"
VOLUNTEER_SUSPENSION_REASON_SEV_2 = "INCIDENT_SEV_2"

# Well-formed UUIDs that never name a persisted row.
UNKNOWN_UUID_A = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_UUID_B = "1b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9"
