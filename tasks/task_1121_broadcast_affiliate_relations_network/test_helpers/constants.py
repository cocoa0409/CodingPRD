"""Domain thresholds and defaults — numeric constants cited across the PRD."""

# Logical clock default at server startup (PRD §2.8).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Posture thresholds (PRD §2.9).
DARK_THRESHOLD_MINUTES = 240             # outage minutes strictly greater-than
DEFICIENT_RATE_THRESHOLD = 0.85          # clearance-rate strictly-less-than
LOCKDOWN_FAILED_COUNT = 3                # failed compliance reports to lock down
PREEMPTION_QUOTA_FRACTION = 0.10         # 10% of clearance_obligation_hours

# Outage-credit formula (PRD §3.7).
OUTAGE_BASE_RATE_CENTS_PER_MIN = 500
OUTAGE_TIER1_MAX_MIN = 30
OUTAGE_TIER2_MAX_MIN = 120
OUTAGE_TIER1_MULT = 1.0
OUTAGE_TIER2_MULT = 1.5
OUTAGE_TIER3_MULT = 2.0
OUTAGE_SATJAM_MULT = 1.5
OUTAGE_PLANNED_MAINT_MULT = 0.0

# Reverse-comp tier thresholds and discounts (PRD §3.6).
TIER_THRESHOLD_MAJOR_CENTS = 100_000_000
TIER_THRESHOLD_LARGE_CENTS = 50_000_000
TIER_THRESHOLD_MID_CENTS = 20_000_000
DISCOUNT_MAJOR = 0.04
DISCOUNT_LARGE = 0.025
DISCOUNT_MID = 0.01

# Renewal offer constraints (PRD §3.4).
VALID_TERM_MONTHS = (12, 24, 36, 48, 60)
MAX_COUNTER_ROUNDS = 3

# Preemption counter cap (PRD §3.3).
COUNTER_ROUND_LIMIT = 3

# Agreement lifecycle windows (PRD §3.2).
EXPIRING_WINDOW_DAYS = 90
RENEWAL_ELIGIBILITY_WINDOW_DAYS = 180

# Defaults used by factories / fixtures.
DEFAULTS = {
    "NETWORK_CALL_SIGN": "PBN",
    "NETWORK_TZ": "America/New_York",
    "REVERSE_COMP_PCT": 0.40,
    "RETRANS_SHARE_PCT": 0.60,
    "CLEARANCE_OBLIGATION_HOURS": 100,
    "GROUP_NAME": "Meridian Media Group",
    "LEVERAGE_TIER": "MID",
    "STATION_CALL_SIGN": "KPBN",
    "DMA_CODE": "DMA-001",
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2027-01-01T00:00:00Z",
    "PROG_TITLE": "Late Show",
    "PROG_START": "2026-06-01T20:00:00Z",
    "PROG_END": "2026-06-01T22:00:00Z",
    "PROG_AVAIL_TOTAL": 20,
    "PROG_AVAIL_LOCAL": 10,
}
