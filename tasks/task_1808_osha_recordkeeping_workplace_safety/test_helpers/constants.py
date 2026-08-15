"""Domain thresholds — numeric constants named in the PRD (§2.6, §2.7, §3)."""

# Rate standardization base (PRD §2.6): 200,000 hours.
HOURS_BASE = 200_000

# Combined days-away + restricted-duty ceiling per case (PRD §3.3).
COMBINED_DAY_CAP = 180

# Recordability determination window (PRD §3.2).
RECORDABILITY_WINDOW_DAYS = 7

# Severe-injury agency-reporting clocks (PRD §3.6).
FATALITY_REPORT_HOURS = 8
STANDARD_REPORT_HOURS = 24

# Citation contest window (PRD §3.8).
CONTEST_WORKING_DAYS = 15

# Risk-score weights (PRD §2.7).
W_LIVE_TRIR = 2.0
W_LIVE_DART = 3.0
W_OVERDUE_CORRECTIVE_ACTION = 5.0
W_OVERDUE_CITATION = 8.0
W_LATE_SEVERE_REPORT = 10.0

# Posture thresholds, inclusive at >= (PRD §2.7).
WATCH_THRESHOLD = 25.0
ELEVATED_THRESHOLD = 50.0

# Logical clock startup default (PRD §2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Shared test defaults.
DEFAULT_YEAR = 2026
DEFAULT_MONTHLY_HOURS = 5000
DEFAULT_MONTHLY_EMPLOYMENT = 10
