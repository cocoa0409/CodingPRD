"""Domain thresholds — numeric constants from PRD calculation rules."""

# Per-state escort/equipment requirement thresholds (whole inches / pounds).
STATE_RULES = {
    "TX": {
        "rear_threshold": 168,
        "front_threshold": 180,
        "two_front_threshold": 192,
        "pole_threshold": 174,
        "police_width_threshold": 192,
        "police_weight_threshold": 200000,
    },
    "OK": {
        "rear_threshold": 168,
        "front_threshold": 174,
        "two_front_threshold": 186,
        "pole_threshold": 168,
        "police_width_threshold": 180,
        "police_weight_threshold": 180000,
    },
    "KS": {
        "rear_threshold": 156,
        "front_threshold": 180,
        "two_front_threshold": 192,
        "pole_threshold": 174,
        "police_width_threshold": 192,
        "police_weight_threshold": 250000,
    },
    "LA": {
        "rear_threshold": 144,
        "front_threshold": 168,
        "two_front_threshold": 180,
        "pole_threshold": 162,
        "police_width_threshold": 180,
        "police_weight_threshold": 150000,
    },
}

CLEARANCE_BUFFER_INCHES = 6

# Pricing
HOURLY_RATE_CENTS = 9000
AVG_SPEED_MPH = 50
POLE_SURCHARGE_CENTS = 15000
POLICE_COORDINATION_FEE_CENTS = 40000
SURVEY_FEE_CENTS = 25000
QUOTE_TTL_HOURS = 72

# Final billing
MIN_ASSIGNMENT_HOURS = 4
ROUNDING_INCREMENT_MINUTES = 30

# Standby billing
STANDBY_GRACE_MINUTES = 30
STANDBY_INCREMENT_MINUTES = 15
STANDBY_RATE_CENTS = 7500

# Invoice composition
VOLUME_TIER1_THRESHOLD_CENTS = 100000
VOLUME_TIER1_PCT = 0.02
VOLUME_TIER2_THRESHOLD_CENTS = 500000
VOLUME_TIER2_PCT = 0.05
FUEL_SURCHARGE_PCT = 0.07

# Incident liability
LIABILITY_CAP_CENTS = 25000000
ESCORT_DEDUCTIBLE_CENTS = 50000

# Escort reliability
RELIABILITY_INITIAL = 100
HIGH_FAULT_THRESHOLD_PCT = 50
HIGH_FAULT_PENALTY = 35
PARTIAL_FAULT_PENALTY = 10
RELIABILITY_SUSPENSION_FLOOR = 40

# Temporal rules
DEADHEAD_BUFFER_MINUTES = 60
COMMS_STALE_MINUTES = 90
DEPART_GRACE_MINUTES = 30

CURFEW_WINDOWS_UTC = {
    "TX": [("07:00", "09:00"), ("16:00", "18:30")],
    "OK": [("07:00", "09:00"), ("16:30", "18:30")],
    "KS": [("06:30", "08:30"), ("16:00", "18:00")],
    "LA": [("06:30", "09:00"), ("15:30", "18:00")],
}

# Standard logical-clock anchor used by scenario setups.
CLOCK_BASE = "2026-08-05T00:00:00Z"

TEST_DEFAULTS = {
    "CARRIER_CREDIT_LIMIT": 10_000_000,
    "WINDOW_START": "2026-08-10T09:00:00Z",
    "WINDOW_END": "2026-08-10T13:00:00Z",
    "PERMIT_VALID_FROM": "2026-08-09T00:00:00Z",
    "PERMIT_VALID_UNTIL": "2026-08-12T00:00:00Z",
}
