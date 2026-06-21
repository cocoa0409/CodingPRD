"""Domain thresholds — numeric constants from PRD calculations and system-wide rules."""

# System-wide pinned constants (PRD §2, §3.3, §3.4, §3.6, §3.10).
COOLING_OFF_DAYS = 7          # cancellation on/before signed_at + 7d is penalty-free
DELINQUENT_AFTER_DAYS = 15    # PAST_DUE -> DELINQUENT at >= 15 whole days (inclusive)
SUSPENDED_AFTER_DAYS = 30     # DELINQUENT -> SUSPENDED at >= 30 whole days (inclusive)
FIXED_MONTH_DAYS = 30         # denominator for the FINAL (fixed-30) dues-proration variant
GUEST_PASS_VALID_DAYS = 14    # expires_at = issued_at + 14 days
PT_CANCEL_CUTOFF_HOURS = 24   # a PT session may not be cancelled within 24h of starts_at
PT_SESSION_MINUTES = 60       # PT busy-block length for member PT time-overlap detection

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Test-default plan shapes used by fixtures and factories.
PLAN_PLUS = {
    "tier": "PLUS",
    "monthly_dues_cents": 6000,
    "included_class_credits": 8,
    "pt_discount_pct": 0.25,
    "contract_term_months": 12,
    "early_termination_fee_cents": 15000,
    "max_freeze_days_per_term": 30,
    "guest_passes_per_cycle": 2,
}

PLAN_BASIC = {
    "tier": "BASIC",
    "monthly_dues_cents": 5000,
    "included_class_credits": 4,
    "pt_discount_pct": 0.0,
    "contract_term_months": 6,
    "early_termination_fee_cents": 10000,
    "max_freeze_days_per_term": 14,
    "guest_passes_per_cycle": 1,
}

PLAN_ELITE = {
    "tier": "ELITE",
    "monthly_dues_cents": 9000,
    "included_class_credits": 12,
    "pt_discount_pct": 0.4,
    "contract_term_months": 12,
    "early_termination_fee_cents": 20000,
    "max_freeze_days_per_term": 45,
    "guest_passes_per_cycle": 4,
}
