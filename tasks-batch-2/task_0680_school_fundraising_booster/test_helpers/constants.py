"""Domain thresholds — numeric constants from the PRD's monetary rules."""

# Sales tax applied once to the order-level gross, rounded half-up (PRD §3.4).
TAX_RATE = 0.0825

# A well-formed UUIDv4-shaped id that does not correspond to any real entity.
# The framework's NON_EXISTENT_UUID is all-zero (not v4-shaped); some validators
# require a syntactically valid UUID before the existence check fires, so this
# v4-shaped value is used for body-FK and path 404 probes.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Default campaign window (logical clock startup default is 2026-04-01T00:00:00Z).
DEFAULT_STARTS_AT = "2026-04-01T00:00:00Z"
DEFAULT_ENDS_AT = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "GOAL_CENTS": 100_000,
    "PROFIT_SPLIT_PCT": 0.50,
    "UNIT_PRICE_CENTS": 2000,
    "UNIT_COST_CENTS": 800,
    "STOCK_QTY": 100,
}
