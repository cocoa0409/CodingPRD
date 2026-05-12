"""Domain thresholds and numeric constants from the PRD.

These mirror the PRD prose verbatim. Test code imports these constants so the
boundary tests carry the same numbers the implementer is contractually told
to honor.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Monetary precision (PRD §2.8)
# ---------------------------------------------------------------------------
TAX_BPS: int = 875                # 8.75% basis-points tax
DEFAULT_REVENUE_SHARE_BPS: int = 7000   # default counselor share, PRD §2.8
SHADOW_PACKAGE_RATE_CENTS: int = 9000   # imputed per-session shadow value (PRD §3.8)
DEFAULT_LIST_PRICE_CENTS: int = 12000   # default Appointment.list_price_cents (PRD §3.8)


# ---------------------------------------------------------------------------
# Slot scheduling invariants (PRD §2.11)
# ---------------------------------------------------------------------------
SLOT_DURATION_MINUTES: int = 60
REST_INTERVAL_MINUTES: int = 15
DAILY_CAP_MINUTES: int = 480       # 8 hours
WEEKLY_CAP_MINUTES: int = 1800     # 30 hours
BOOKING_PRE_START_BUFFER_HOURS: int = 1
RESCHEDULE_PRE_START_BUFFER_HOURS: int = 24
HOLD_TTL_MINUTES: int = 15
START_EARLY_WINDOW_MINUTES: int = 5
START_LATE_WINDOW_MINUTES: int = 15
NO_SHOW_THRESHOLD_MINUTES: int = 30


# ---------------------------------------------------------------------------
# Refund tiers (PRD §3.5)
# ---------------------------------------------------------------------------
REFUND_FULL_HOURS: int = 24        # >=24h -> FULL on cancel; >24h -> FULL on estimate
REFUND_PARTIAL_HOURS: int = 2      # >=2h -> PARTIAL on cancel; >2h -> PARTIAL on estimate
REFUND_PARTIAL_MULTIPLIER: float = 0.50


# ---------------------------------------------------------------------------
# Certification windows (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
CYCLE_1_REQUIRED_SUPERVISION_HOURS: float = 40.0
CYCLE_N_REQUIRED_SUPERVISION_HOURS: float = 20.0
REQUIRED_CE_HOURS: float = 12.0
CYCLE_1_WINDOW_DAYS: int = 365
CYCLE_N_WINDOW_DAYS: int = 730
UNDER_REVIEW_GRACE_DAYS: int = 14


# ---------------------------------------------------------------------------
# Risk scoring (PRD §3.7)
# ---------------------------------------------------------------------------
RISK_LOOKBACK_DAYS: int = 90
RISK_ACUTE_THRESHOLD: int = 8
RISK_ELEVATED_THRESHOLD: int = 4
RISK_HIGH_POINTS: int = 5
RISK_MEDIUM_POINTS: int = 3
RISK_LOW_POINTS: int = 1
RISK_COUNSELOR_TRIGGERED_BONUS: int = 1


# ---------------------------------------------------------------------------
# Crisis follow-up (PRD §3.7)
# ---------------------------------------------------------------------------
FOLLOW_UP_HOURS: int = 72


# ---------------------------------------------------------------------------
# Supervision overlap (PRD §3.10)
# ---------------------------------------------------------------------------
SUPERVISION_BUFFER_MINUTES: int = 30


# ---------------------------------------------------------------------------
# Counseling-record retention (PRD §2.10)
# ---------------------------------------------------------------------------
RETENTION_YEARS: int = 7


# ---------------------------------------------------------------------------
# Payout window
# ---------------------------------------------------------------------------
PAYOUT_REVERSAL_WINDOW_DAYS: int = 7   # PRD §3.9


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Risk keywords (PRD §3.6)
# ---------------------------------------------------------------------------
RISK_KEYWORDS = ("suicide", "self-harm", "kill myself", "end it")


# ---------------------------------------------------------------------------
# Specialty / channel sets (PRD §3.1)
# ---------------------------------------------------------------------------
ALL_SPECIALTY_TAGS = (
    "ANXIETY", "DEPRESSION", "TRAUMA", "FAMILY",
    "ADDICTION", "ADOLESCENT", "EATING_DISORDER", "GRIEF",
)
ALL_CHANNELS = ("TEXT", "AUDIO", "VIDEO")


# ---------------------------------------------------------------------------
# Time anchor (test-driving clock)
# ---------------------------------------------------------------------------
DEFAULT_T0 = "2026-06-01T00:00:00.000Z"   # used by fixtures via /_clock/advance
