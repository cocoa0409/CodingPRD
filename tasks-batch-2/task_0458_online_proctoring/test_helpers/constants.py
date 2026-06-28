"""Domain thresholds — numeric constants from the Online Proctoring PRD calculations."""

# §2.4 — server logical clock startup default
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# §3.2 — appointment effective-window computation
SETUP_MINUTES = 10

# §2.6 — integrity-score severity weights and auto-void threshold
SEVERITY_WEIGHT = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 40}
RECORD_REVIEW_MINOR_WEIGHT = 2.5  # MINOR halved under RECORD_REVIEW only
AUTO_VOID_THRESHOLD = 50          # strict: score < 50 voids

# §2.7 — proctor load
MODE_WEIGHT = {"LIVE": 1.0, "RECORD_REVIEW": 0.4}
MAX_LOAD_FACTOR = 1.0
DEFAULT_CONCURRENT_CAPACITY = 4

# §3.1 — institution defaults
DEFAULT_REPORT_THRESHOLD_SCORE = 70

# §3.1 — accommodation default
DEFAULT_EXTRA_TIME_PCT = 0
