"""Domain thresholds — numeric constants from the PRD's calculation and
deadline rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Identification breadth rule constants (PRD §3.4).
THRESHOLDS = {
    "THREE_PROPERTY_MAX_COUNT": 3,
    "TWO_HUNDRED_PCT_MULTIPLIER": 2,
}

# Statutory deadline spans measured in calendar days from Day-0 (PRD §3.3).
DEADLINES = {
    "ID_DEADLINE_DAYS": 45,
    "EXCHANGE_DEADLINE_DAYS": 180,
}

# Standard relinquished-leg figures used across the fixtures: a FORWARD
# property of FMV 500000, expenses 30000, payoff 120000, basis 180000 yields
# net_proceeds 350000 and realized_gain 290000.
TEST_DEFAULTS = {
    "FMV": 500000,
    "SELLING_EXPENSES": 30000,
    "MORTGAGE_PAYOFF": 120000,
    "ADJUSTED_BASIS": 180000,
    "NET_PROCEEDS": 350000.00,
    "REALIZED_GAIN": 290000.00,
}

# Logical-clock anchors used by the deadline tests. The server boots at
# 2026-01-01T00:00:00Z; Day-0 is set to 2026-03-01 so the 45-day deadline
# lands on 2026-04-15 and the 180-day deadline on 2026-08-28.
CLOCK = {
    "BOOT_DEFAULT": "2026-01-01T00:00:00Z",
    "DAY_ZERO": "2026-03-01T00:00:00Z",
    "ID_DEADLINE": "2026-04-15T00:00:00Z",
    "ID_DEADLINE_PLUS_ONE_DAY": "2026-04-16T00:00:00Z",
    "EXCHANGE_DEADLINE": "2026-08-28T00:00:00Z",
    "EXCHANGE_DEADLINE_PLUS_ONE_DAY": "2026-08-29T00:00:00Z",
    "WITHIN_WINDOW": "2026-03-15T00:00:00Z",
    "AFTER_ALL_DEADLINES": "2026-09-01T00:00:00Z",
}

# ISO-8601 representations with the three fractional digits the PRD mandates.
TIMESTAMPS = {
    "DAY_ZERO": "2026-03-01T00:00:00.000Z",
    "ID_DEADLINE": "2026-04-15T00:00:00.000Z",
    "EXCHANGE_DEADLINE": "2026-08-28T00:00:00.000Z",
}
