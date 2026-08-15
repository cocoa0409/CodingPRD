"""Domain thresholds and standard fixture constants (PRD §2.4, §3.1, §3.2)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Standard term calendar/policy used across scenarios (PRD §3.1).
STD_TERM = {
    "code": "FALL-26",
    "name": "Fall 2026",
    "start_date": "2026-08-24",
    "end_date": "2026-12-11",
    "census_date": "2026-09-07",
    "full_refund_end_date": "2026-09-07",
    "mid_refund_end_date": "2026-10-05",
    "withdrawal_deadline": "2026-11-13",
    "refund_policy": "SCHEDULE_TIERED",
    "flat_fee_cents": 15000,
    "hold_threshold_cents": 20000,
    "plan_setup_fee_cents": 2500,
    "late_fee_pct": 0.05,
    "grace_days": 10,
}

# Standard IN_STATE / UNDERGRADUATE rate card (PRD §3.1).
STD_RATE = {
    "residency": "IN_STATE",
    "level": "UNDERGRADUATE",
    "per_credit_rate_cents": 35000,
    "full_time_threshold_credits": 12,
    "flat_rate_cents": 420000,
    "max_flat_credits": 18,
    "overload_rate_cents": 35000,
    "effective_from": "2026-08-01",
    "effective_to": "2026-12-31",
}

# Derived amounts under STD_TERM + STD_RATE (per-credit branch < 12 credits;
# flat branch at >= 12; overload per credit above 18).
STD_FLAT_FEE_CENTS = STD_TERM["flat_fee_cents"]
STD_PER_CREDIT_CENTS = STD_RATE["per_credit_rate_cents"]
STD_FLAT_RATE_CENTS = STD_RATE["flat_rate_cents"]

THRESHOLDS = {
    "HOLD_THRESHOLD_CENTS": STD_TERM["hold_threshold_cents"],
    "PLAN_SETUP_FEE_CENTS": STD_TERM["plan_setup_fee_cents"],
    "LATE_FEE_PCT": STD_TERM["late_fee_pct"],
    "GRACE_DAYS": STD_TERM["grace_days"],
    "FULL_TIME_THRESHOLD_CREDITS": STD_RATE["full_time_threshold_credits"],
    "MAX_FLAT_CREDITS": STD_RATE["max_flat_credits"],
    "PRO_RATA_CUTOFF": 0.60,
    "COLLECTIONS_FEE_PCT": 0.05,
    "MIN_INSTALLMENTS": 2,
    "MAX_INSTALLMENTS": 6,
    "MIN_CREDIT_HOURS": 1,
    "MAX_CREDIT_HOURS": 24,
}
