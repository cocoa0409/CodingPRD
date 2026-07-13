"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"

# Test-report pass thresholds (PRD §3.3)
MIN_RELIEF_DIFFERENTIAL_PSID = 2.0
MIN_CHECK_PSID = 1.0

# Hazard-survey weighted scoring (PRD §3.5)
WEIGHT_PREMISE = 0.3
WEIGHT_CHEMICAL = 0.4
WEIGHT_AUXILIARY = 0.3
HIGH_WEIGHTED_THRESHOLD = 70
MODERATE_WEIGHTED_THRESHOLD = 40
CHEMICAL_HIGH_FLOOR = 35
AUXILIARY_MODERATE_FLOOR = 30

# Penalty accrual (PRD §3.6, §2.8)
BASE_DAILY_RATE_CENTS = 333
RISK_MULTIPLIER = {"LOW": 1.0, "MODERATE": 1.5, "HIGH": 2.0}

# Shutoff-notice cure windows (PRD §3.6)
GRACE_DAYS = {"LOW": 30, "MODERATE": 14, "HIGH": 7}

# Compliance-posture upcoming-due lead window (PRD §2.6)
REMINDER_LEAD_DAYS = 30

# Appointment premises buffer (PRD §3.2)
PREMISES_BUFFER_MINUTES = 60

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
