"""Domain thresholds — numeric constants from PRD calculations and policy defaults."""

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Contract policy defaults (PRD §3.1)
CONTRACT_DEFAULTS = {
    "AGENT_COMMISSION_PCT": 0,
    "RESERVE_PCT": 0.25,
    "RESERVE_HOLD_PERIODS": 2,
}

# Author default (PRD §3.1)
AUTHOR_DEFAULTS = {
    "TAX_WITHHOLDING_PCT": 0,
}

# Title default (PRD §3.2)
TITLE_DEFAULTS = {
    "EDITION": 1,
}

# Tier boundary used throughout the worked examples (PRD §3.7 escalator).
TIER_BOUNDARY_INCLUSIVE_UPPER = 5000
