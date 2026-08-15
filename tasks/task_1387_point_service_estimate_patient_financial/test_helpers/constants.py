"""Domain thresholds and shared fixtures' numeric constants (PRD §2.4, §3).

All money is integer cents; all percents are integer percent (PRD §2.4).
"""

THRESHOLDS = {
    # PRD §3.4: high-dollar threshold, inclusive boundary.
    "HIGH_DOLLAR_THRESHOLD_CENTS": 1000000,
    # PRD §3.9: dispute overage threshold, inclusive boundary.
    "GFE_DISPUTE_THRESHOLD_CENTS": 40000,
    # PRD §3.3 / §3.5: required deposit percentage of accepted responsibility.
    "REQUIRED_DEPOSIT_PCT": 25,
    # PRD §3.2: snapshot freshness TTL in days (strictly-greater comparison).
    "SNAPSHOT_TTL_DAYS": 30,
    # PRD §3.6: refund tiers in business days before service.
    "REFUND_FULL_WINDOW_BD": 2,
    "REFUND_PARTIAL_PCT": 50,
    # PRD §3.8: installment count range and first-due-date offset.
    "MIN_INSTALLMENTS": 2,
    "MAX_INSTALLMENTS": 12,
    "FIRST_DUE_DAYS": 30,
    # PRD §3.8: default sweep grace period past an installment due date.
    "PLAN_DEFAULT_GRACE_DAYS": 14,
    # PRD §3.9: variance tolerance band, inclusive.
    "VARIANCE_TOLERANCE_PCT": 10.00,
    # PRD §3.5: good-faith delivery windows in business days.
    "GFE_FULL_WINDOW_BD": 10,
    "GFE_SHORT_WINDOW_BD": 3,
    "GFE_FULL_DEADLINE_BD": 3,
    "GFE_SHORT_DEADLINE_BD": 1,
}

# Logical-clock instants reused across setups (PRD §2.4 logical clock).
CLOCK_START = "2026-08-03T09:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical insured benefit scenario ("INS-A" style inputs shared by many
# workflows): snapshot deductible 150000/50000, OOP 600000/100000, coins 20,
# contracted rate 3000000 -> allowed 3000000, deductible 100000,
# coinsurance 580000, responsibility 500000 (OOP-capped), deposit 125000.
INS_A = {
    "CPT_CODE": "27447",
    "LIST_PRICE_CENTS": 5000000,
    "RATE_CENTS": 3000000,
    "PAYER_CODE": "ACME",
    "BUNDLING_RULE": "MULTIPLE_PROCEDURE_REDUCTION",
    "REDUCTION_PCT": 50,
    "EFFECTIVE_FROM": "2026-01-01",
    "SERVICE_DATE": "2026-08-20",
    "DEDUCTIBLE_TOTAL_CENTS": 150000,
    "DEDUCTIBLE_MET_CENTS": 50000,
    "OOP_MAX_CENTS": 600000,
    "OOP_MET_CENTS": 100000,
    "COINSURANCE_PCT": 20,
    # Derived per the PRD §3.4 formulas:
    "EXPECTED_ALLOWED_CENTS": 3000000,
    "EXPECTED_DEDUCTIBLE_CENTS": 100000,
    "EXPECTED_COINSURANCE_CENTS": 580000,
    "EXPECTED_RESPONSIBILITY_CENTS": 500000,
    "EXPECTED_INSURANCE_PAYS_CENTS": 2500000,
    "EXPECTED_REQUIRED_DEPOSIT_CENTS": 125000,
}
