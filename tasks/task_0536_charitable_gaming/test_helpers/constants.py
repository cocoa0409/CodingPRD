"""Domain thresholds — numeric constants from the Charitable Gaming PRD calculations (§3)."""

# §3.1 Organization eligibility
ELIGIBILITY_MIN_MONTHS = 36
QUALIFYING_NONPROFIT_TYPES = ["501C3", "501C4", "501C8", "501C10", "501C19"]

# §3.2 Annual prize limit fixed at license creation by license_type
ANNUAL_PRIZE_LIMIT_CENTS = {"BINGO": 1_000_000, "RAFFLE": 2_000_000, "COMBINED": 3_000_000}

# §3.4 Per-occasion prize cap by occasion_type
PER_OCCASION_PRIZE_CAP_CENTS = {"BINGO": 800_000, "RAFFLE": 1_500_000}

# §3.7 Proceeds distribution allowances
ADMIN_ALLOWANCE_PCT = 0.15
REGULATORY_FEE_PCT = 0.05

# §3.8 Violation points and suspension threshold
POINTS_BY_TYPE = {
    "LATE_REPORT": 3,
    "PRIZE_LIMIT_EXCEEDED": 6,
    "UNREGISTERED_EQUIPMENT": 5,
    "PROCEEDS_MISUSE": 10,
}
SUSPENSION_POINT_THRESHOLD = 10
REPORT_GRACE_DAYS = 7

# §3.6 Equipment allocation buffer
EQUIPMENT_BUFFER_DAYS = 1

# §2.5 Logical clock startup default
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
