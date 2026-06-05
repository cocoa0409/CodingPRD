"""Domain thresholds and numeric constants for the Contract Lifecycle Management API.

Sourced from the PRD's risk-scoring, cost-estimate, and pagination rules.
Generic NON_EXISTENT_UUID comes from the framework.
"""

# Risk-scoring constants (PRD §2.8).
MANDATORY_MISS_PENALTY = 25
SCORE_CEILING = 100
SCORE_FLOOR = 0

# Legal-review cost-estimate constants (PRD §3.8), all integer cents.
BASE_CENTS = 50000
TIER1_RATE_CENTS = 10000   # first 3 deviations
TIER2_RATE_CENTS = 7500    # 4th through 8th deviation
TIER3_RATE_CENTS = 5000    # 9th onward

# Per-clause risk-weight valid range (PRD §3.1).
RISK_WEIGHT_MIN = 0
RISK_WEIGHT_MAX = 40

# Organization defaults / ranges (PRD §2.8, §3.1).
DEFAULT_RISK_APPETITE_THRESHOLD = 60
DEFAULT_AUTO_RENEW_LEAD_DAYS = 30
RISK_APPETITE_THRESHOLD_MIN = 0
RISK_APPETITE_THRESHOLD_MAX = 100

# Contract-template defaults (PRD §3.1).
DEFAULT_TERM_MONTHS = 12

# Pagination (PRD §2.3).
DEFAULT_LIMIT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
DEFAULT_OFFSET = 0


def cost_estimate_for(deviation_count: int) -> int:
    """Marginal, tiered legal-review cost in integer cents (PRD §3.8).

    First 3 deviations @ TIER1, next 5 (4th-8th) @ TIER2, 9th onward @ TIER3.
    Provided for cross-checking; tests still assert the PRD-precomputed literal.
    """
    n = deviation_count
    total = BASE_CENTS
    total += min(n, 3) * TIER1_RATE_CENTS
    if n > 3:
        total += min(n - 3, 5) * TIER2_RATE_CENTS
    if n > 8:
        total += (n - 8) * TIER3_RATE_CENTS
    return total
