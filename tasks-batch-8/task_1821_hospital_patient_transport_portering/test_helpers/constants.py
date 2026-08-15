"""Domain thresholds — numeric constants from PRD §3 calculations.

PRD §3.4 travel estimate, §3.6 service levels, §3.7 cleaning dwell,
§3.3 patient separation, §3.8 staffing adequacy.
"""

# Logical clock startup default (PRD §2.5).
CLOCK_START = "2026-08-01T00:00:00Z"

# Covering shift window used by fixtures so clock-in always has coverage.
COVERING_SHIFT_START = "2026-07-31T00:00:00Z"
COVERING_SHIFT_END = "2026-09-01T00:00:00Z"

# Response-time service level targets per priority (PRD §3.6).
TARGET_RESPONSE_MINUTES = {"ROUTINE": 120, "URGENT": 45, "STAT": 15}

# At-risk watermark: three-quarters of the target, floored (PRD §3.6).
AT_RISK_NUM = 3
AT_RISK_DEN = 4

# Offer time-to-live; strictly more than this expires (PRD §3.4).
OFFER_TTL_MINUTES = 10

# DEEP cleaning dwell; exactly this many minutes suffices (PRD §3.7).
DWELL_MINUTES_DEEP = 15

# Patient minimum separation; exactly this many minutes apart is allowed (PRD §3.3).
PATIENT_MIN_SEPARATION_MINUTES = 75

# Travel estimate constants (PRD §3.4 / §3.5).
EQUIPMENT_FACTOR = {
    "PORTER_ONLY": 1.0,
    "WHEELCHAIR": 1.1,
    "STRETCHER": 1.25,
    "BARIATRIC_STRETCHER": 1.4,
}
OXYGEN_SETUP_MINUTES = 2
CONGESTION_SURCHARGE_PER_TRIP = 2
CONGESTION_CAP = 5

# Delay-record cascade multiplier by destination location_type (PRD §3.6).
LOCATION_MULTIPLIER = {
    "OR": 2.0,
    "IMAGING": 1.5,
    "WARD": 1.0,
    "ICU": 1.0,
    "ED": 1.0,
    "DISCHARGE_LOUNGE": 1.0,
    "OTHER": 1.0,
}

# Default asset tags per equipment type used by fixtures.
DEFAULT_ASSET_TAGS = {
    "WHEELCHAIR": "WC-001",
    "STRETCHER": "ST-001",
    "BARIATRIC_STRETCHER": "BS-001",
}

# Standard directed-edge pair used by most fixtures:
# HUB -> W4 (8 base / 12 airborne), W4 -> IMG (10 base / 16 airborne).
EDGE_HUB_WARD = (8, 12)
EDGE_WARD_IMG = (10, 16)

TEST_DEFAULTS = {
    "PATIENT_REF": "P1",
    "CLINICIAN_ID": "clin-1",
}
