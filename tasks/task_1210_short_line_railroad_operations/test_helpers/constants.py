"""Domain thresholds — numeric constants stated in the PRD narratives (§3)."""

# PRD §3.6: per-class base speeds and defect caps (integer mph).
CLASS_SPEED_MPH = {
    "EXCEPTED": 10,
    "CLASS_1": 10,
    "CLASS_2": 25,
    "CLASS_3": 40,
    "CLASS_4": 60,
    "CLASS_5": 80,
}
DEFECT_CAP_MPH = {
    "MONITOR": 25,
    "CRITICAL": 10,
}

# PRD §3.6: inspection frequency per class, in days.
INSPECTION_FREQ_DAYS = {
    "EXCEPTED": 30,
    "CLASS_1": 7,
    "CLASS_2": 7,
    "CLASS_3": 3,
    "CLASS_4": 2,
    "CLASS_5": 1,
}

# PRD §3.7: hours-of-service limits (integer minutes).
HOS_DAILY_LIMIT_MINUTES = 720
HOS_MONTHLY_LIMIT_MINUTES = 16560
HOS_REQUIRED_REST_MINUTES = 600

# PRD §3.3: minimum car-hire charge applied at close (integer cents).
MIN_HIRE_CENTS = 3600

# PRD §3.2: demurrage tariff per car per billable day (integer cents).
DEMURRAGE_PER_CAR_PER_DAY_CENTS = 7500

# PRD §3.5: per-ton commodity rates (integer cents).
COMMODITY_RATE_CENTS_PER_TON = {
    "GRAIN": 38500,
    "LUMBER": 42000,
    "CHEMICALS": 51500,
}

# PRD §2.4: the logical clock's fixed startup reading.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# PRD §3.1: customer creation default for the free-day allowance.
DEFAULT_DEMURRAGE_FREE_DAYS = 2
