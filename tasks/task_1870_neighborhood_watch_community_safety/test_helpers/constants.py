"""Domain thresholds — numeric constants named in the PRD's calculation and
validation prose (participation weights, heat buckets, certification tiers,
fan-out relay, quorum fraction, depot budget, strike limit, quiet hours)."""

# Logical clock
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Participation score weights (PRD: participation score variants)
PARTICIPATION = {
    "BLOCK_W": 10,
    "MEMBER_W": 2,
    "MEETING_W": 5,
    "EVENT_W": 8,
    "INCIDENT_W": 3,
}

# Block risk heat step-decay buckets (whole days from occurred_at to clock)
HEAT = {
    "FULL_WINDOW_DAYS": 30,
    "HALF_WINDOW_DAYS": 60,
    "QUARTER_WINDOW_DAYS": 90,
    "FULL_WEIGHT": 1.0,
    "HALF_WEIGHT": 0.5,
    "QUARTER_WEIGHT": 0.25,
}

# Certification points composite
CERTIFICATION = {
    "APPROVAL_THRESHOLD": 60,
    "CONDITIONAL_FLOOR": 40,
    "FULL_THRESHOLD": 80,
    "MEMBER_CAP": 25,
    "MEETING_CAP": 25,
    "GRANT_MONTHS_FULL": 24,
    "GRANT_MONTHS_PARTIAL": 12,
}

# Alert fan-out
FANOUT = {
    "PHONE_TREE_RELAY": 2.5,
    "FLYER_RATIO": 10,
}

# Meeting quorum
QUORUM = {
    "FRACTION": 0.25,
    "MIN": 2,
}

# Materials stewardship
DEPOT_SIGN_BUDGET = 50

# Member conduct
STRIKE_LIMIT = 3

# Quiet hours window (local, daily): 22:00-07:00; INCIDENT_BULLETIN exempt
QUIET_HOURS = {"START_HOUR": 22, "END_HOUR": 7}

# Large-gathering permit tier
PERMIT_TIER_ATTENDANCE = 100

# Street-closure buffer (hours prepended/appended to event windows)
CLOSURE_BUFFER_HOURS = 2

# Training cooling-off period (hours after a completed session)
TRAINING_COOLDOWN_HOURS = 24
