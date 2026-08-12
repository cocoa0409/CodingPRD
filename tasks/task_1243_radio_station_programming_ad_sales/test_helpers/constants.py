"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Well-known calendar anchors: 2026-05-01 is a Friday.
DATE_FRI = "2026-05-01"
DATE_SAT = "2026-05-02"
DATE_MON = "2026-05-04"
DATE_TUE = "2026-05-05"
DATE_WED = "2026-05-06"

# Spot unit rate tiers (PRD §3.2).
RATINGS_TIERS = [(2.0, 0.80), (4.0, 1.00), (6.0, 1.25)]  # lower bounds; >= 6.0 -> 1.50
RATINGS_MULT_TOP = 1.50
DOW_FACTOR_WEEKEND = 0.85
DEMAND_TIERS = [(0.70, 1.00), (0.85, 1.15)]  # u >= 0.85 -> 1.30
DEMAND_MULT_TOP = 1.30

# Daypart hour sets (PRD §3.6).
DAYPART_HOURS = {
    "MORNING_DRIVE": {5, 6, 7, 8},
    "MIDDAY": {9, 10, 11, 12, 13},
    "AFTERNOON_DRIVE": {15, 16, 17, 18},
    "EVENING": {19, 20, 21},
    "OVERNIGHT": {0, 1, 2, 3, 4},
}

# Affidavit billing (PRD §3.8).
AGENCY_COMMISSION_PCT = 0.15

# Spot durations allowed at booking (PRD §3.6); live reads 30/60 (PRD §3.10).
SPOT_DURATIONS = [15, 30, 60]
LIVE_READ_DURATIONS = [30, 60]
