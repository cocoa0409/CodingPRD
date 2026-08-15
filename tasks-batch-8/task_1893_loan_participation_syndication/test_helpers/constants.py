"""Domain thresholds and numeric constants from the PRD (§2.4, §3.1-§3.9)."""

# Logical clock fixed startup default (PRD §2.4).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

# Facility governance defaults (PRD §3.1).
DEFAULT_MAJORITY_THRESHOLD_BPS = 5001
DEFAULT_SUPERMAJORITY_THRESHOLD_BPS = 6667
DEFAULT_QUORUM_BPS = 5000
DEFAULT_VOTING_WINDOW_DAYS = 15
DEFAULT_MIN_TRANSFER_CENTS = 1_000_000

# Unanimous consent threshold (PRD §3.6).
UNANIMOUS_THRESHOLD_BPS = 10_000

# Funding window and late-funding penalty rate (PRD §3.3).
FUNDING_WINDOW_DAYS = 5
LATE_FUNDING_DAILY_BPS = 15

# Buyback penalty rate for SERVICING_BREACH (PRD §3.9).
BUYBACK_PENALTY_BPS = 500

# Share scale (PRD §2.6).
SHARE_SCALE_BPS = 10_000

# Fee denominator (PRD §3.5).
FEE_DENOMINATOR_DAYS = 360

# Statement due-date offsets in days (PRD §3.8).
QUARTERLY_STATEMENT_DUE_DAYS = 45
ANNUAL_STATEMENT_DUE_DAYS = 90

# Solicitation buffer in hours (PRD §3.6).
SOLICITATION_BUFFER_HOURS = 24

# Transfer settlement blackout half-width in days around a payment value date (PRD §3.9).
BLACKOUT_HALF_WIDTH_DAYS = 2

# Standard scenario defaults used across fixtures.
DEFAULTS = {
    "CURRENCY": "USD",
    "INTEREST_RATE_BPS": 1200,
    "SERVICING_FEE_BPS": 25,
    "DEFAULT_INTEREST_ADDON_BPS": 800,
    "MATURITY_DATE": "2031-08-01",
    "DRAW_START": "2026-08-01",
    "DRAW_END": "2027-08-01",
}
