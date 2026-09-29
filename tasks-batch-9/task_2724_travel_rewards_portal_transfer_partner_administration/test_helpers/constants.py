"""
Pinned numeric and calendar constants taken verbatim from the PRD.

Nothing here is invented: every figure is a literal the specification states, so
a test that needs the earn multiplier for `LEGACY_GOLD` or the inclusive posture
threshold reads it from one place instead of restating it.
"""

# ─── The logical clock (§2.4) ─────────────────────────────────────────

#: "Before any client sets it, the clock reads `2026-08-01T00:00:00.000Z`."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"


# ─── Card products (§3.3, §3.6) ──────────────────────────────────────

#: "1.5 for `PREMIER`, 1.0 for `CORE`, and 2.0 for `LEGACY_GOLD`" (§3.3).
PRODUCT_EARN_MULTIPLIER = {
    "PREMIER": 1.5,
    "CORE": 1.0,
    "LEGACY_GOLD": 2.0,
}

#: "1.25 cents per point for `PREMIER`, 1.0 for `CORE`, and 1.5 for
#: `LEGACY_GOLD`" (§3.6).
PRODUCT_REDEMPTION_CENTS_PER_POINT = {
    "PREMIER": 1.25,
    "CORE": 1.0,
    "LEGACY_GOLD": 1.5,
}


# ─── Statement credits (§3.6) ────────────────────────────────────────

#: "`statement_credit_cents` is `points_requested` multiplied by one cent".
STATEMENT_CREDIT_CENTS_PER_POINT = 1.0

#: "A statement credit must be for at least 2,500 points".
STATEMENT_CREDIT_MIN_POINTS = 2500


# ─── Transfers (§3.8) ────────────────────────────────────────────────

#: "The transfer is then divided into blocks of 1,000 points each".
BLOCK_POINTS = 1000


# ─── Agencies and parity (§3.5) ──────────────────────────────────────

#: "Both basis-point figures must be at least 0 and no more than 5000".
MIN_BPS = 0
MAX_BPS = 5000

#: "`invoice_terms_days` defaults to 30 when omitted."
DEFAULT_INVOICE_TERMS_DAYS = 30

#: Basis-point denominator used by markup, parity, bonus and breakage maths.
BPS_DENOMINATOR = 10000


# ─── Fraud scoring (§3.9) ────────────────────────────────────────────

#: "a device change contributes 30, a new payee 25, an email change 20,
#: a password reset 15, and a geographic anomaly 10."
SIGNAL_WEIGHTS = {
    "DEVICE_CHANGE": 30,
    "NEW_PAYEE": 25,
    "EMAIL_CHANGE": 20,
    "PASSWORD_RESET": 15,
    "GEO_ANOMALY": 10,
}

#: "the sum of the weights of the case's distinct signals, capped at 100".
INSTANT_SCORE_CAP = 100

#: "strictly after the instant 30 days before the case's own `created_at`".
VELOCITY_LOOKBACK_DAYS = 30

#: "that window total is divided by 50,000 using integer floor division,
#: multiplied by 10, and capped at 40."
VELOCITY_STEP_POINTS = 50000
VELOCITY_STEP_SCORE = 10
VELOCITY_TERM_CAP = 40

#: "a device-stability credit of 10, granted only when
#: `device_fingerprint_changed` is false".
DEVICE_STABLE_CREDIT = 10

#: "a score of exactly 60 locks, a score of exactly 30 watches, and exactly
#: two holds watch."
POSTURE_LOCK_SCORE = 60
POSTURE_WATCH_SCORE = 30
POSTURE_WATCH_HOLD_COUNT = 2

#: `review_score` is "clamped below at 0 and above at 100".
REVIEW_SCORE_MIN = 0
REVIEW_SCORE_MAX = 100


# ─── Liability and breakage (§3.11) ──────────────────────────────────

#: "Below 1,000,000 gross outstanding points the base breakage rate is 1200
#: basis points; from 1,000,000 up to but not including 10,000,000 it is 1800
#: basis points; at 10,000,000 and above it is 2400 basis points."
BREAKAGE_TIER_ONE_CEILING = 1_000_000
BREAKAGE_TIER_TWO_CEILING = 10_000_000
BREAKAGE_TIER_ONE_BPS = 1200
BREAKAGE_TIER_TWO_BPS = 1800
BREAKAGE_TIER_THREE_BPS = 2400

#: "the base rate plus 1000 basis points, capped at 5000 basis points."
DORMANT_UPLIFT_BPS = 1000
BREAKAGE_RATE_CAP_BPS = 5000

#: "no `EARN_BASE` and no `EARN_BONUS` entry whose `occurred_at` falls strictly
#: after the instant 365 days before `as_of`".
DORMANCY_LOOKBACK_DAYS = 365

#: "Should the chosen input set be empty, the blended cost falls back to 1000
#: cents per 1,000 points."
DEFAULT_COST_PER_1K_CENTS = 1000

#: The per-thousand-points divisor of §3.11 steps four, five and §3.6.
POINTS_PER_THOUSAND = 1000


# ─── Programme change notices (§3.10) ────────────────────────────────

#: "the notice's `effective_at` is at least 45 days after the clock instant".
MIN_NOTICE_DAYS = 45


# ─── Pagination (§2.3) ───────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ─── Sweep counters (§2.10) ──────────────────────────────────────────

#: "The sweep returns a count for each step" — these eight names, in order.
SWEEP_COUNTERS = (
    "rotations_activated",
    "rotations_expired",
    "bonus_events_opened",
    "bonus_events_closed",
    "notices_made_effective",
    "grandfather_windows_matured",
    "transfers_completed",
    "entitlements_expired",
)
