"""Domain thresholds — numeric constants from PRD §2.5/§3 workflows."""

# Benchmark durations by procedure class (PRD §3.3).
BENCHMARK_MINUTES = {"MINOR": 45, "STANDARD": 90, "COMPLEX": 180}

# Turnover gap base by procedure class, plus hybrid-room bonus (PRD §3.3).
TURNOVER_BASE_MINUTES = {"MINOR": 15, "STANDARD": 25, "COMPLEX": 40}
HYBRID_TURNOVER_BONUS = 10

# Surgeon duration bias (PRD §3.3).
BIAS_MIN_HISTORY = 5
BIAS_WINDOW = 20
BIAS_CLAMP_LO = 0.800
BIAS_CLAMP_HI = 1.250
BIAS_DEFAULT = 1.000

# Prime-time window: weekdays 07:00 (420) through 17:00 (1020, exclusive) (PRD §3.7).
PRIME_WINDOW_START = 420
PRIME_WINDOW_END = 1020

# First-case on-time grace: delay <= 10 is on-time (PRD §3.6).
FIRST_CASE_GRACE_MINUTES = 10

# Slot floor: a free fragment shorter than thirty minutes is forfeited (PRD §2.10).
MIN_SLOT_MINUTES = 30

# Committee quorum (PRD §3.7).
COMMITTEE_QUORUM = 3

# Block reduction keeps nine tenths of original_minutes (PRD §3.7).
REDUCTION_KEEP_PCT = 0.9

# Service line default release deadline (PRD §3.1).
DEFAULT_RELEASE_DEADLINE_HOURS = 72

# Logical clock default before any set call (PRD §2.9).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Common scheduling dates used across the suite (all UTC weekdays unless noted).
DATE_FRIDAY = "2026-05-01"    # Friday (default clock date)
DATE_SATURDAY = "2026-05-02"  # Saturday (zero prime overlap)
DATE_MONDAY = "2026-05-04"    # Monday
DATE_NEXT_MONDAY = "2026-05-11"
CLOCK_AFTER_WEEK = "2026-05-08T00:00:00Z"
