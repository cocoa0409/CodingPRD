"""Domain thresholds -- numeric constants from PRD sections 2 and 3."""

# Logical clock (PRD section 2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Project defaults (PRD section 3.1)
DEFAULT_SHIFT_START = "07:00"
DEFAULT_SHIFT_HOURS = 8
DEFAULT_RETENTION_DAYS = 2555
DEFAULT_BUFFER_MINUTES = 30

# Manpower bands (PRD section 3.3)
OT_FLOOR_HOURS = 8
DT_FLOOR_HOURS = 12
OT_BAND_WIDTH = 4

# Weather lost-day classification (PRD section 3.4)
LOST_DAY_THRESHOLD_RATIO = 0.5

# T&M pricing (PRD section 3.7)
OT_MULT = 1.5
DT_MULT = 2.0
STANDBY_MULT = 0.5
TIER_CAP_CENTS = 100000
MARKUP_LOW_PCT = 0.10
MARKUP_HIGH_PCT = 0.05

# OSHA notification deadlines (PRD section 3.5)
FATALITY_NOTIFY_HOURS = 8
LOST_TIME_NOTIFY_HOURS = 24

# Incident narrative minimum length for recordable severities (PRD section 3.5)
RECORDABLE_NARRATIVE_MIN_CHARS = 50

TEST_DEFAULTS = {
    "REPORT_DATE": "2026-08-05",
    "REPORT_DATE_ISO_NOON": "2026-08-05T12:00:00Z",
    # Clock position used to submit a 2026-08-05 report (after the workday).
    "SUBMIT_CLOCK": "2026-08-05T17:00:00Z",
    "BUDGETED_QUANTITY": 100,
    "UNIT_COST_CENTS": 1000,
    "WORKER_COUNT": 2,
    "HOURS_PER_WORKER": 8,
    "DELIVERED_QTY": 100,
}
