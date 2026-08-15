"""Domain thresholds — numeric constants from the PRD (§2.5, §2.8, §3)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Member readiness scoring (PRD §3.1).
W_CHECKIN = 50
CHECKIN_TARGET = 6
W_DRILL = 30
DRILL_TARGET = 2
BONUS_NO_SHOW_FREE = 20
PRIVILEGE_PENALTY = 50
TIER_ELIGIBLE_MIN = 70
TIER_PROVISIONAL_MIN = 40

# Field day scoring (PRD §3.6).
PER_CONTACT_CAP = 10
BONUS_THRESHOLD = 100
BONUS_POINTS = 100
MODE_BASE_POINTS = {"CW": 2, "DIGITAL": 2, "PHONE": 1}
POWER_MULTIPLIER = {"QRP": 5, "LOW": 2, "HIGH": 1}
VHF_BONUS_BANDS = {"B6M", "B2M"}
BAND_BONUS = 2

# Equipment late fee (PRD §3.8).
DAILY_RATE_CENTS = 150
DAMAGE_RATE = 0.10
LOAN_MAX_WINDOW_DAYS = 90

# Membership dues (PRD §3.1).
ANNUAL_DUES_CENTS = 3600
RENEWAL_PERIOD_DAYS = 365

# Exam pass threshold (PRD §3.7).
EXAM_PASS_PERCENT = 74
LICENSE_RENEWAL_DAYS_ON_PASS = 3650

# Coordination frequency allocations in MHz (PRD §3.2).
FREQUENCY_BANDS_MHZ = ((144.0, 148.0), (420.0, 450.0))

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
