"""Domain thresholds and numeric constants from the PRD (§2.6, §2.10, §3)."""

# Compliance / standing (PRD §2.6)
REQUIRED_CLEANUPS_PER_YEAR = 3
ROLLING_WINDOW_DAYS = 365
GRACE_DAYS = 180
TERM_MONTHS = 24

# Supply allocation (PRD §3.5)
BAGS_PER_VOLUNTEER_MILE = 2
WATER_SURCHARGE = 1.25
GRABBER_DIVISOR = 2

# Debris weight estimation — per-bag averages in pounds (PRD §3.6)
AVG_BAG_WEIGHT_LBS = {
    "GENERAL_TRASH": 12.75,
    "RECYCLABLES": 7.25,
    "METALS": 22.4,
    "YARD_WASTE": 10.6,
    "OTHER": 9.85,
}

# Minor age (PRD §3.4)
MAJORITY_AGE = 18

# Temporal windows
EVENT_MIN_LEAD_DAYS = 14
REPORT_WINDOW_DAYS = 30
RENEWAL_WINDOW_DAYS_BEFORE_TERM_END = 90

# Logical clock startup default (PRD §2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"
