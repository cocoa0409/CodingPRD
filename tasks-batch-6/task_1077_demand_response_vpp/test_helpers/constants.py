"""Domain thresholds — numeric constants from the PRD's calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Baseline measurement constants (PRD §3.6).
BASELINE_LOOKBACK = 5
BASELINE_TOP_N = 3
WEATHER_ADJUST_FACTOR = 1.10

# Per-dispatch tiered payout constants (PRD §3.7).
OVERPERFORM_THRESHOLD = 1.10
BONUS_MULTIPLIER = 1.15
NET_FLOOR_CENTS = 0

# Event-window buffer (PRD §3.4): two hours (120 minutes) on each side.
EVENT_BUFFER_MINUTES = 120

# Default program rate configuration used across fixtures.
DEFAULT_INCENTIVE_RATE_CENTS_PER_KWH = 50
DEFAULT_PENALTY_RATE_CENTS_PER_KWH = 80
DEFAULT_CAPACITY_INCENTIVE_CENTS_PER_KW = 1000
DEFAULT_PERFORMANCE_FLOOR_PCT = 0.75
DEFAULT_NOTIFICATION_LEAD_MINUTES = 60
DEFAULT_MAX_EVENTS_PER_SEASON = 3

DEFAULT_SEASON_START = "2026-05-01T00:00:00Z"
DEFAULT_SEASON_END = "2026-09-30T00:00:00Z"

# The logical clock boots at this instant (PRD §2.10).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
