"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_BOOKING_DATE = "2026-08-01"

THRESHOLDS = {
    # monthly charge (PRD §3.3)
    "TIER1_LIMIT_HOURS": 50,
    "TIER1_RATE_CENTS": 5000,
    "TIER2_RATE_CENTS": 7500,
    "CYCLE_RATIO_NUM": 1,
    "CYCLE_RATIO_DEN": 2,
    "CYCLE_SURCHARGE_CENTS": 25000,
    # transition slot buffer (PRD §3.8)
    "TRANSITION_BUFFER_DAYS": 2,
    # re-inspection cap (PRD §3.6)
    "MAX_REINSPECTIONS": 1,
}

# Severity uplift factors for the provisional compensation estimate (PRD §3.6)
UPLIFT = {
    "CRITICAL": 1.50,
    "MAJOR": 1.25,
    "MINOR": 1.10,
}

REQUIRED_DOC_TYPES = ["BIRTH_RECORD", "AIRWORTHINESS_CERT", "ENGINE_LOG", "LLP_STATUS"]

# Fixed return-condition checklist template: (item_code, severity) in sort order
CHECKLIST_TEMPLATE = [
    ("AIRFRAME", "CRITICAL"),
    ("ENGINE", "MAJOR"),
    ("INTERIOR", "MINOR"),
    ("PAINT", "MINOR"),
]

TEST_DEFAULTS = {
    "MONTHLY_RENT_CENTS": 1_000_000,
    "RESERVE_RATE_PER_FH_CENTS": 4000,
    "RESERVE_RATE_PER_FC_CENTS": 8000,
    "MONTHLY_HOUR_CAP": 300,
    "LEASE_START_DATE": "2026-08-01",
    "LEASE_END_DATE": "2027-08-01",
    "MODEL": "A320-200",
    "MANUFACTURE_DATE": "2012-05-17",
    "PERIOD_MONTH": "2026-08",
}
