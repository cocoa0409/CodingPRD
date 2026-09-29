"""Domain thresholds and constants taken from the PRD's calculations and gates."""

# ─── Rate-card pricing (PRD §3.3) ────────────────────────────────────────────
# Declared defaults every optional rate-card field falls back to.
RATE_CARD_DEFAULTS = {
    "tier1_max_seconds": 30,
    "tier2_max_seconds": 120,
    "tier2_rate_multiplier": 1.25,
    "tier3_rate_multiplier": 1.60,
    "media_multiplier_theatrical": 1.40,
    "media_multiplier_broadcast": 1.15,
    "media_multiplier_streaming": 1.30,
    "media_multiplier_all_media": 1.75,
    "territory_multiplier_world": 1.50,
    "territory_multiplier_domestic": 1.00,
    "term_multiplier_per_year": 0.20,
    "festival_window_multiplier": 0.35,
    "all_media_window_multiplier": 1.00,
}

# Seconds in one billable unit, and the tier-1 rate multiplier.
SECONDS_PER_BILLABLE_UNIT = 30
TIER1_RATE_MULTIPLIER = 1.00
MONTHS_PER_TERM_YEAR = 12

# ─── E&O premium rating (PRD §3.7) ───────────────────────────────────────────
EO_BASE_RATE = 0.0125
EO_RETENTION_CREDIT_RATE = 0.30
EO_MIN_PREMIUM_CENTS = 25000
EO_RISK_WEIGHTS = {
    "LICENSED": 0.010,
    "FAIR_USE": 0.045,
    "PUBLIC_DOMAIN": 0.004,
}
EO_DEPICTION_SURCHARGE = 0.008
EO_MIN_COVERAGE_LIMIT_CENTS = 100000

# ─── Fair-use scoring (PRD §3.5) ─────────────────────────────────────────────
FAIR_USE_ACCEPT_THRESHOLD = 0.6000
FAIR_USE_SCORE_DECIMAL_PLACES = 4
FAIR_USE_WEIGHTS = {
    "TRANSFORMATIVE_WEIGHTED": {
        "transformative_score": 0.45,
        "nature_score": 0.10,
        "amount_used_score": 0.15,
        "market_harm_score": 0.30,
    },
    "MARKET_HARM_WEIGHTED": {
        "transformative_score": 0.20,
        "nature_score": 0.10,
        "amount_used_score": 0.20,
        "market_harm_score": 0.50,
    },
}

# ─── Ceilings and windows ────────────────────────────────────────────────────
NEGOTIATION_ROUND_LIMIT = 6            # PRD §3.4 — a round is accepted only below 6
RELEASE_REVISION_LIMIT = 3             # PRD §3.6 — revisions permitted below 3
RENEWAL_WINDOW_DAYS = 60               # PRD §3.8 — 0..60 whole days inclusive
EXPIRY_WARNING_WINDOW_DAYS = 60        # PRD §3.8 step three
DEPICTION_QUIET_BUFFER_DAYS = 30       # PRD §3.6 quiet buffer
POSTURE_RESTRICTED_OPEN_FACTOR = 4     # PRD §2.8 rule 4 — open * 4 <= total

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Logical clock (PRD §2.11) ───────────────────────────────────────────────
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ─── Cascade text stamped by the system ──────────────────────────────────────
AUTO_WITHDRAWAL_RATIONALE = "AUTO: supporting opinion letter withdrawn"


def auto_suspension_reason(sweep_epoch: int) -> str:
    """The text stamped onto a package suspended by the sweep (PRD §3.8 step four)."""
    return f"AUTO: production posture BLOCKED at sweep epoch {sweep_epoch}"


# ─── Test data defaults (the standard card of the PRD §3.3 worked example) ───
TEST_DEFAULTS = {
    "base_rate_per_30s_cents": 60000,
    "minimum_fee_cents": 150000,
    "festival_minimum_fee_cents": 40000,
    "effective_from_date": "2026-01-01",
    "term_start_date": "2026-08-15",
    "term_end_date": "2029-08-15",
    "term_months": 36,
    # A 45-second BROADCAST / WORLD / 36-month licence on the standard card.
    "all_media_window_fee_cents": 362250,
    "festival_only_fee_cents": 126788,
}
