"""Domain thresholds and shared test inputs derived from PRD §2 and §3.

Tests reference these names rather than re-typing numeric literals so
boundary tests stay in lockstep with PRD prose.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Settlement waterfall constants (PRD §3.9)
# ---------------------------------------------------------------------------
# PRD §3.9 step 1: 'the ticket's paid_amount_cents multiplied by
# PLATFORM_COMMISSION_BPS (800 basis points, or 8 percent) divided by 10000'.
PLATFORM_COMMISSION_BPS = 800

# PRD §3.9 step 5: 'net_after_platform multiplied by TAX_BPS (600 basis
# points, or 6 percent)'.
TAX_BPS = 600

# PRD §3.9 step 6: 'if any ticket ... carries a non-empty promo_code, the
# effective share is PROMO_DISTRIBUTOR_BPS_OVERRIDE (5000 basis points,
# or 50/50)'.
PROMO_DISTRIBUTOR_BPS_OVERRIDE = 5000


# ---------------------------------------------------------------------------
# Anomaly thresholds (PRD §3.5)
# ---------------------------------------------------------------------------
# PRD §3.5: 'if this count would reach 10 or more with the proposed ticket
# included, the rule trips with rule ROLLING_WINDOW'.
ROLLING_WINDOW_THRESHOLD = 10
# PRD §3.5: 'if this count would reach 30 or more with the proposed ticket
# included, the rule trips with rule CUMULATIVE'.
CUMULATIVE_THRESHOLD = 30
# PRD §3.5: 'within the last 60 minutes inclusive of the current server clock'.
WINDOW_MINUTES = 60


# ---------------------------------------------------------------------------
# Attendance / fiscal thresholds (PRD §3.7, §3.5)
# ---------------------------------------------------------------------------
# PRD §3.7: 'the resulting attendance_rate_bps must be strictly less than
# 1500 (15.00 percent)'.
LOW_ATTENDANCE_THRESHOLD_BPS = 1500

# PRD §3.5: 'the count of VALID tickets for the same showtime_id and same
# buyer_external_id must remain strictly less than the per-buyer hard cap
# of 20 tickets -- the 20th sale to a single buyer is admitted, the 21st
# is rejected'.
PER_BUYER_HARD_CAP = 20


# ---------------------------------------------------------------------------
# Showtime block format setups (PRD §3.4)
# ---------------------------------------------------------------------------
# PRD §3.4: 'a format-specific setup overhead is added: 5 minutes for IMAX,
# 3 minutes for 3D, and 0 minutes for 2D'.
IMAX_SETUP_MINUTES = 5
THREEDEE_SETUP_MINUTES = 3
TWODEE_SETUP_MINUTES = 0


# ---------------------------------------------------------------------------
# Competing-film cap (PRD §3.4)
# ---------------------------------------------------------------------------
# PRD §3.4: 'at most one showtime per distributor_id per business_date is
# permitted to start inside that window for the cinema'.
COMPETING_PEAK_CAP = 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
# PRD §2.3: 'limit defaults to 10, has a minimum of 1, and a maximum of 100'.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Default screen / cinema inputs used by fixtures
# ---------------------------------------------------------------------------
# Cinema peak window default per PRD §3.3.
DEFAULT_PEAK_START_MIN = 1080  # 18:00
DEFAULT_PEAK_END_MIN = 1380    # 23:00 (exclusive)

# Screen defaults expressed independently of PRD defaults --
# every fixture explicitly passes the value it cares about.
DEFAULT_TRAILER_MIN = 10
DEFAULT_AD_MIN = 5
DEFAULT_CLEANING_INTERVAL_MIN = 15

# A wide operating window so the default block fits comfortably.
WIDE_OPERATING_START_MIN = 0
WIDE_OPERATING_END_MIN = 1440

# Region codes
DEFAULT_REGION = "REG_A"
ALT_REGION = "REG_B"


# Default release timestamp -- a comfortable future-yet-test-mode anchor.
# Tests use /_clock/advance to step the server clock to or past this point
# before exercising release/sweep transitions.
DEFAULT_RELEASE_DATE = "2026-05-04T00:00:00.000Z"
DEFAULT_BUSINESS_DATE = "2026-05-05T00:00:00.000Z"
# A presale instant slightly before the business date.
DEFAULT_PRESALE_OPENS_AT = "2026-05-04T12:00:00.000Z"


__all__ = [
    "PLATFORM_COMMISSION_BPS",
    "TAX_BPS",
    "PROMO_DISTRIBUTOR_BPS_OVERRIDE",
    "ROLLING_WINDOW_THRESHOLD",
    "CUMULATIVE_THRESHOLD",
    "WINDOW_MINUTES",
    "LOW_ATTENDANCE_THRESHOLD_BPS",
    "PER_BUYER_HARD_CAP",
    "IMAX_SETUP_MINUTES",
    "THREEDEE_SETUP_MINUTES",
    "TWODEE_SETUP_MINUTES",
    "COMPETING_PEAK_CAP",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_PEAK_START_MIN",
    "DEFAULT_PEAK_END_MIN",
    "DEFAULT_TRAILER_MIN",
    "DEFAULT_AD_MIN",
    "DEFAULT_CLEANING_INTERVAL_MIN",
    "WIDE_OPERATING_START_MIN",
    "WIDE_OPERATING_END_MIN",
    "DEFAULT_REGION",
    "ALT_REGION",
    "DEFAULT_RELEASE_DATE",
    "DEFAULT_BUSINESS_DATE",
    "DEFAULT_PRESALE_OPENS_AT",
]
