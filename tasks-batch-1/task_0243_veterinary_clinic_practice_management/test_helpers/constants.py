"""Domain thresholds — numeric constants from PRD calculations (Section 3) and
the monetary/scheduling rules in Sections 2-3.
"""

# Standard flat vaccine fee, identical for every vaccine code (PRD 3.4 / 3.2).
STANDARD_VACCINE_FEE_CENTS = 4500

# Reminder lead: reminder_at = next_due_at - 14 days (PRD 3.4).
REMINDER_LEAD_DAYS = 14

# Minimum re-dose interval in whole days per vaccine code (PRD 3.4).
MIN_INTERVAL_DAYS = {
    "RABIES": 365,
    "DHPP": 21,
    "BORDETELLA": 180,
    "FVRCP": 21,
}

# Wellness tier -> service discount fraction (PRD 3.2).
SERVICE_DISCOUNT_PCT = {
    "BASIC": 0.10,
    "PLUS": 0.20,
    "PREMIER": 0.30,
}

# Wellness tier -> bundled-vaccine allotment at enrollment (PRD 3.2).
BUNDLED_VACCINES_AT_ENROLLMENT = {
    "BASIC": 2,
    "PLUS": 4,
    "PREMIER": 8,
}

# Projected-savings reference annual service spend (PRD 3.2).
REFERENCE_ANNUAL_SERVICE_CENTS = 60000

# Surgery tiered pricing constants (PRD 3.8).
PROCEDURE_BASE_CENTS = 20000
ANES_RATE_SMALL_CENTS = 800     # weight <= 5 kg
ANES_RATE_MEDIUM_CENTS = 600    # 5 < weight <= 25 kg
ANES_RATE_LARGE_CENTS = 500     # weight > 25 kg
FREE_MINUTES = 60
TIME_RATE_CENTS_PER_MIN = 150
MIN_SURGERY_CENTS = 25000
MAX_SURGERY_CENTS = 500000

# Controlled-substance refill cooldown in days (PRD 3.5).
CONTROLLED_COOLDOWN_DAYS = 30

# Appointment reschedule cap (PRD 3.3).
RESCHEDULE_LIMIT = 3

# Operatory default cleanup buffer in minutes (PRD 3.8).
DEFAULT_CLEANUP_BUFFER_MINUTES = 30

THRESHOLDS = {
    "STANDARD_VACCINE_FEE_CENTS": STANDARD_VACCINE_FEE_CENTS,
    "REMINDER_LEAD_DAYS": REMINDER_LEAD_DAYS,
    "REFERENCE_ANNUAL_SERVICE_CENTS": REFERENCE_ANNUAL_SERVICE_CENTS,
    "PROCEDURE_BASE_CENTS": PROCEDURE_BASE_CENTS,
    "FREE_MINUTES": FREE_MINUTES,
    "TIME_RATE_CENTS_PER_MIN": TIME_RATE_CENTS_PER_MIN,
    "MIN_SURGERY_CENTS": MIN_SURGERY_CENTS,
    "MAX_SURGERY_CENTS": MAX_SURGERY_CENTS,
    "CONTROLLED_COOLDOWN_DAYS": CONTROLLED_COOLDOWN_DAYS,
    "RESCHEDULE_LIMIT": RESCHEDULE_LIMIT,
}

# A syntactically valid UUID that resolves to no resource.
NON_EXISTENT_UUID_LOCAL = "00000000-0000-4000-8000-000000000000"
