"""Domain thresholds — numeric constants from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework; these are PRD-domain values.
"""

# Plan-loading multipliers applied to per-acre premium (PRD §3.4).
RATE_MULTIPLIER = {
    "YP": 1.00,
    "RP": 1.15,
    "RP_HPE": 1.08,
}

# Federal subsidy factors, looked up by exact coverage_level key (PRD §3.4).
SUBSIDY_FACTORS = {
    0.50: 0.67,
    0.55: 0.64,
    0.60: 0.64,
    0.65: 0.59,
    0.70: 0.59,
    0.75: 0.55,
    0.80: 0.48,
    0.85: 0.38,
}

# Agent-commission tier boundaries on total_premium_cents (PRD §3.8).
COMMISSION_TIER_1_CEIL_CENTS = 500000      # below this -> rate 0.10
COMMISSION_TIER_2_CEIL_CENTS = 1000000     # at..this inclusive -> rate 0.08; above -> 0.06
COMMISSION_RATE_TIER_1 = 0.10
COMMISSION_RATE_TIER_2 = 0.08
COMMISSION_RATE_TIER_3 = 0.06

# Allowed coverage levels (PRD §3.3).
ALLOWED_COVERAGE_LEVELS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]

# A coverage_level value that is NOT in the allowed set (for negative tests).
INVALID_COVERAGE_LEVEL = 0.72

# A UUID that resolves to no resource (for FK / not-found tests).
NONEXISTENT_FK_UUID = "00000000-0000-4000-8000-000000000999"
