"""Domain thresholds and shared fixture constants (PRD §2.4, §3.3, §3.5, §3.2)."""

# PRD §2.4: the logical clock reads exactly 2026-05-01T00:00:00Z before any advance.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-05-01"

# PRD §3.2: month-to-month premium of 1,500 basis points (fifteen percent).
MTM_PREMIUM_BPS = 1500

# PRD §3.3: term discount of ten bps per month beyond twelve, capped at 180.
TERM_DISCOUNT_PER_MONTH_BPS = 10
MAX_TERM_DISCOUNT_BPS = 180

# PRD §3.5: inclusive approval authority tiers, in basis points.
AGENT_MAX_CONCESSION_BPS = 300
MANAGER_MAX_CONCESSION_BPS = 800
ABSOLUTE_MAX_CONCESSION_BPS = 2000

# PRD §3.4: negotiation is bounded at three rounds.
MAX_NEGOTIATION_ROUNDS = 3

# PRD §3.4: response deadline is fourteen days from issue (bounded by term end).
RESPONSE_WINDOW_DAYS = 14
# PRD §3.4: execution deadline is ten days from acceptance.
EXECUTION_WINDOW_DAYS = 10
# PRD §3.6: cure deadline is ten days from service.
CURE_WINDOW_DAYS = 10
# PRD §3.7: rescission window is three days from countersign.
RESCISSION_WINDOW_DAYS = 3

# Shared policy fixture "CA-OAK": base 400 + CPI 150 vs hard ceiling 900
# -> effective cap 550 bps; high-increase threshold 500 bps; notice 60/90;
# non-renewal lead 60.
CA_OAK = {
    "jurisdiction_code": "CA-OAK",
    "base_cap_bps": 400,
    "cpi_adjustment_bps": 150,
    "hard_ceiling_bps": 900,
    "high_increase_threshold_bps": 500,
    "notice_days_low": 60,
    "notice_days_high": 90,
    "non_renewal_notice_days": 60,
}
CA_OAK_EFFECTIVE_CAP_BPS = 550

# Common lease geometry used across the suite: 12-month term starting
# 2026-06-01, half-open end 2027-06-01, rent 200000 cents.
STD_TERM_START = "2026-06-01"
STD_TERM_MONTHS = 12
STD_TERM_END = "2027-06-01"
STD_RENT_CENTS = 200000
