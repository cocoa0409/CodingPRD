"""Domain thresholds — numeric constants from the PRD's fee and risk formulas
(§3.2, §3.5, §3.6, §3.9) and the temporal windows (§3.6, §3.7).

NON_EXISTENT_UUID comes from the framework (re-exported via __init__).
"""

# Base fee by risk tier, used by both the estimate (§3.2) and the final fee (§3.5).
BASE_FEE = {"LOW": 100.00, "MEDIUM": 250.00, "HIGH": 600.00}

# Per-employee surcharge and zoning variance surcharge (§3.2 / §3.5).
PER_EMPLOYEE_FEE = 5.00
ZONING_VARIANCE_SURCHARGE = 150.00

# Per passed-inspection fee added only into the binding issuance fee (§3.5).
PER_INSPECTION_FEE = 75.00

# Base renewal fee by risk tier, used as the delinquency-penalty base (§3.6).
RENEWAL_FEE = {"LOW": 200.00, "MEDIUM": 480.00, "HIGH": 900.00}

# Delinquency penalty tier breakpoints (whole UTC days overdue) and rates (§3.6).
GRACE_PERIOD_DAYS = 30      # days_overdue <= 30 -> 0% penalty
TIER_A_MAX_DAYS = 60        # 31..60 -> 10%
TIER_B_MAX_DAYS = 90        # 61..90 -> 25%; > 90 -> 50%

# Temporal windows (§3.6, §3.7).
RENEWAL_WINDOW_DAYS = 60        # renewal opens at expires_on - 60 days
REVOCATION_THRESHOLD_DAYS = 90  # revocation requires days_overdue > 90

# Transfer fee components (§3.9).
FLAT_TRANSFER_FEE = 300.00
RISK_TRANSFER_SURCHARGE = 200.00  # added only when license risk_tier == HIGH

# Compliance-risk-score weights (§3.4 provisional / §3.6 audited).
VIOLATION_WEIGHT = 5
VIOLATION_CAP = 30
DELINQUENCY_WEIGHT = 20
PRIOR_REVOCATION_WEIGHT = 10
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

# Pagination bounds (§2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10

# Convenient grouped views for tests that prefer dict access.
THRESHOLDS = {
    "GRACE_PERIOD_DAYS": GRACE_PERIOD_DAYS,
    "TIER_A_MAX_DAYS": TIER_A_MAX_DAYS,
    "TIER_B_MAX_DAYS": TIER_B_MAX_DAYS,
    "RENEWAL_WINDOW_DAYS": RENEWAL_WINDOW_DAYS,
    "REVOCATION_THRESHOLD_DAYS": REVOCATION_THRESHOLD_DAYS,
    "VIOLATION_WEIGHT": VIOLATION_WEIGHT,
    "VIOLATION_CAP": VIOLATION_CAP,
    "DELINQUENCY_WEIGHT": DELINQUENCY_WEIGHT,
    "PRIOR_REVOCATION_WEIGHT": PRIOR_REVOCATION_WEIGHT,
}
