"""Domain thresholds and numeric constants from the PRD calculations (PRD §2.9, §3.8).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Basis-point arithmetic (PRD §2.9, §3.5).
BPS_DENOM = 100               # one bps denominator
POINTS_DIVISOR = 1_000_000    # 100 * 100 * 100: cat/quarterly, tier, cents->points

# Redemption value (PRD §3.8): statement credit is a flat 1 cent per point.
STATEMENT_CREDIT_CENTS_PER_POINT = 1

# Implicit tier-0 multiplier in basis points (PRD §3.1, §3.5).
IMPLICIT_TIER_MULTIPLIER_BPS = 100
