"""Domain thresholds — numeric constants from the PRD's calculation and temporal rules."""

# Logical clock startup default (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Temporal terms / windows (PRD §3.4, §3.7, §3.8, §3.5)
PERMIT_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 30
RENEWAL_GRACE_DAYS = 30
CURE_PERIOD_DAYS = 30
REMOVAL_COMPLIANCE_DAYS = 15
REGISTRATION_TERM_DAYS = 365
INSPECTION_BUFFER_MINUTES = 60

# Sign permit fee (provisional and final share this schedule) (PRD §3.4)
BASE_FEE_BY_TYPE = {"WALL": 15000, "MONUMENT": 25000, "DIGITAL": 50000}
AREA_INCLUDED_SQFT = 32
AREA_TIER1_CAP_SQFT = 100
AREA_TIER1_RATE_CENTS = 200
AREA_TIER2_RATE_CENTS = 350
ILLUMINATION_SURCHARGE = {"NONE": 0, "EXTERNAL": 5000, "DIGITAL_DISPLAY": 20000}

# Billboard registration fee (PRD §3.8)
BASE_FACE_FEE_CENTS = 3333
DIGITAL_FACE_MULTIPLIER = 1.5
DIGITAL_FACE_FEE_CENTS = 5000  # round_half_up(3333 * 1.5)

# Non-conforming amortization (PRD §3.6)
DECLINE_RATE = 0.20

# Illumination ranking (PRD §3.2)
ILLUMINATION_RANK = {"NONE": 0, "EXTERNAL": 1, "DIGITAL_DISPLAY": 2}

# Default WALL / 40 sqft / NONE fee used by many setups: 15000 + 8*200 + 0
DEFAULT_WALL_FEE_CENTS = 16600

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
