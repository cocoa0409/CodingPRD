"""Domain thresholds and rates — numeric constants from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Default logical clock at server startup (PRD §2.9).
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Sales tax (PRD §3.4 Deal amount due).
TAX_RATE = 0.0725

# Trade-in appraisal grade factors and hour penalty (PRD §3.3).
GRADE_FACTORS = {
    "EXCELLENT": 1.00,
    "GOOD": 0.85,
    "FAIR": 0.65,
    "POOR": 0.40,
}
HOUR_PENALTY_PER_100 = 0.01
HOUR_PENALTY_CAP = 0.40

# Lease residual percentages and money factors by credit tier (PRD §3.4).
RESIDUAL_PCT = {"PRIME": 0.55, "STANDARD": 0.50, "SUBPRIME": 0.45}
MONEY_FACTOR = {"PRIME": 0.0010, "STANDARD": 0.0015, "SUBPRIME": 0.0022}

# Floor-plan interest accrual (PRD §3.2).
DAYS_PER_YEAR = 365
BPS_DENOMINATOR = 10000

# Floor-plan curtailment schedule (PRD §3.2).
CURTAIL_DAY_STAGE1 = 90
CURTAIL_DAY_STAGE2 = 180
CURTAIL_DAY_STAGE3 = 270
CURTAIL_PCT_PER_STAGE = 0.10

# Warranty reimbursement (PRD §3.7).
WARRANTY_LABOR_CAP_PCT = 0.90
PARTIAL_FACTOR = 0.50

# Whole-goods deposit and discount bands (PRD §3.8).
DISCOUNT_PCT = {"EARLY_ORDER": 0.12, "IN_SEASON": 0.05, "LATE": 0.00}
DEPOSIT_PCT = 0.10
DEPOSIT_FLOOR_PER_UNIT_CENTS = 50000
