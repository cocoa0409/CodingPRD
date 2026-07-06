"""Domain thresholds — numeric constants stated in the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework. Note: the delivery
turnaround buffer (TURNAROUND_BUFFER_MIN) is named only symbolically in the
PRD and carries no numeric value, so it is deliberately NOT defined here.
"""

# Pricing / loyalty / tax (PRD §2.5, §3.5, §3.6).
PLUS_DISCOUNT_FACTOR = 0.10          # PLUS members: goods x (1 - 0.10)
TAX_RATE = 0.08                      # 8% on taxable base
LOYALTY_DIVISOR = 100               # 1 base point per 100 cents

# Inventory (PRD §3.9).
SHRINK_QUARANTINE_G = 200            # shrink strictly greater than this quarantines

# Container deposits by type (PRD §3.3).
DEPOSIT_BY_TYPE = {
    "GLASS_500": 150,
    "GLASS_1000": 250,
    "BYO": 0,
}

# Pagination (PRD §2.3).
PAGINATION_DEFAULTS = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Logical clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
