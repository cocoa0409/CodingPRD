"""Domain thresholds — numeric constants named in the PRD (§3 business rules)."""

# Logical clock (PRD §2.4): startup default before any set call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_QUEUE_DATE = "2026-08-01"

# At-risk score (PRD §3.2).
GPA_BAND_LOW_CUT = 2.0   # gpa below 2.0 -> base 40
GPA_BAND_MID_CUT = 2.5   # 2.0 <= gpa < 2.5 -> base 25; gpa >= 2.5 -> base 10
GPA_BASE_LOW_BAND = 40
GPA_BASE_MID_BAND = 25
GPA_BASE_HIGH_BAND = 10
SEVERITY_BOOST = {"HIGH": 20, "MEDIUM": 12, "LOW": 6}
NO_SHOW_POINTS = 10
NO_SHOW_CAP = 3
INTERVENTION_WEIGHT = 10
HOLD_WEIGHT = 8
TIER_HIGH_MIN = 70
TIER_MEDIUM_MIN = 40
MAX_SCORE = 100

# Advisor load weights per advisee risk tier (PRD §3.1).
RISK_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

# Referral service levels in days (PRD §3.6).
SLA_DAYS = {"HIGH": 2, "MEDIUM": 5, "LOW": 10}
MAX_OUTREACH_ATTEMPTS = 3

# Degree plans (PRD §3.8).
MAX_TERM_CREDITS = 18

# Drop-in queue (PRD §3.5).
DROPIN_MAX_ACTIVE_TICKETS = 3

# Appointments (PRD §3.4).
MIN_APPOINTMENT_MINUTES = 15
MAX_APPOINTMENT_MINUTES = 60
CHECK_IN_WINDOW_MINUTES = 10
NO_SHOW_GRACE_MINUTES = 10
