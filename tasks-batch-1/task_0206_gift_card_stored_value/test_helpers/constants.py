"""Domain thresholds and defaults — numeric constants from the PRD's program config,
balance/pricing rules, and dormancy/escheat policy (§2.7, §3.1, §3.8, §3.9).
"""

# Program-wide defaults (PRD §3.1).
PROGRAM_DEFAULTS = {
    "DEFAULT_CURRENCY": "USD",
    "RELOAD_MIN_CENTS": 500,
    "RELOAD_MAX_BALANCE_CENTS": 100000,
    "HOLD_TTL_SECONDS": 900,
    "B2B_DISCOUNT_PCT": 0.035,
}

# StateRule / dormancy / escheat defaults (PRD §3.1, §3.8).
STATE_RULE_DEFAULTS = {
    "DEFAULT_ESCHEAT_RATE": 0.60,
    "DORMANCY_THRESHOLD_MONTHS_DEFAULT": 12,
}

# Fixed dormancy fee (PRD §3.8): the fee is min(200, settled_balance_cents).
DORMANCY_FEE_CENTS = 200
