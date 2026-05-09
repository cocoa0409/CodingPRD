"""Domain thresholds — numeric constants from PRD calculations."""

# ─── Review-path / fraud thresholds (PRD §3.3, §3.5) ─────────────
# "AUTO if and only if claimed_amount_cents is less than or equal to the
#  auto-approval threshold of 200,000 cents (that is, 2,000 dollars)"
AUTO_APPROVAL_THRESHOLD_CENTS = 200_000

# "the auto-fraud gate of 0.30: a fraud_score strictly less than 0.30 is
#  eligible for the auto path"
AUTO_FRAUD_GATE = 0.30

# "If that score reaches or exceeds 0.80, the transition out of
#  UNDER_INVESTIGATION is blocked"
FRAUD_HOLD_THRESHOLD = 0.80

# ─── Repair-shop trust decay (PRD §3.5) ──────────────────────────
DECAY_PER_FLAG = 0.20
BLACKLIST_THRESHOLD = 0.40
COLLUSION_PATTERN_THRESHOLD = 3
LOOKBACK_DAYS = 90

# ─── Fraud-score weights (PRD §3.5) ──────────────────────────────
W_PATTERN = 0.30
W_COLLUSION = 0.30
W_FORGERY = 0.30
W_RAPID = 0.10

# ─── Idempotency window (PRD §2.6) ───────────────────────────────
IDEMPOTENCY_WINDOW_HOURS = 24

# ─── Policy reporting window default (PRD §2.6) ──────────────────
DEFAULT_REPORTING_WINDOW_DAYS = 30

# ─── Pagination (PRD §2.3) ───────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# ─── Convenience defaults for tests ──────────────────────────────
DEFAULTS = {
    # Policy financial defaults — chosen to give clean integer payouts.
    "DEDUCTIBLE_CENTS": 100_000,         # $1,000
    "COINSURANCE_RATIO": 0.8000,
    "COVERAGE_LIMIT_CENTS": 1_000_000,   # $10,000
    "REPORTING_WINDOW_DAYS": 30,

    # Claim defaults
    "CLAIMED_AMOUNT_CENTS": 600_000,
    "ASSESSED_LOSS_CENTS": 500_000,

    # Estimate line item default
    "ESTIMATE_AMOUNT_CENTS": 500_000,

    # Admin token (test deployments)
    "ADMIN_TOKEN": "test-admin-token",
}

# Days/seconds helpers
SECONDS_PER_DAY = 86_400
