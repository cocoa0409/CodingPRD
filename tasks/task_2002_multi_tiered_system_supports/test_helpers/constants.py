"""Domain thresholds and policy constants named in the PRD."""

# District policy knob defaults (PRD §3.1)
DEFAULT_SPED_REFERRAL_MIN_WEEKS = 12
DEFAULT_FIDELITY_THRESHOLD_PCT = 80

# Aimline projection constants (PRD §3.6): total probe count by frequency
WEEKLY_TOTAL_PROBES = 8
BIWEEKLY_TOTAL_PROBES = 4

# Probe cadence intervals in days (PRD §3.5/§3.6)
WEEKLY_PROBE_INTERVAL_DAYS = 7
BIWEEKLY_PROBE_INTERVAL_DAYS = 14

# Referral evaluation timeline (PRD §3.9): consent + 60 calendar days
EVALUATION_DUE_DAYS = 60

# Outcome report small-cohort rule (PRD §3.9)
SMALL_COHORT_THRESHOLD = 30
SMALL_COHORT_PENALTY = 5

SUBGROUP_CODES = ["ELL", "FRL", "IEP", "BLACK", "HISPANIC", "WHITE", "ASIAN", "MULTI"]

# Common screening cut-point pairs used across tests
DEFAULT_TIER2_MAX = 100
DEFAULT_TIER3_MAX = 70

# Logical-clock defaults (PRD §2.7)
CLOCK_DEFAULT_START = "2026-08-01T00:00:00Z"
FALL_WINDOW_OPENS = "2026-08-01"
FALL_WINDOW_CLOSES = "2026-08-31"
CLOCK_IN_FALL_WINDOW = "2026-08-05T00:00:00Z"
WINTER_WINDOW_OPENS = "2026-12-01"
WINTER_WINDOW_CLOSES = "2026-12-15"
CLOCK_IN_WINTER_WINDOW = "2026-12-05T00:00:00Z"
