"""Domain thresholds — numeric constants from the PRD billing/pricing rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pricing / billing constants (PRD §3.3, §3.7).
DEFAULT_HOURLY_RATE_CENTS = 12000   # quote default zone rate when no tech dispatched
DISPATCH_FEE_CENTS = 8900           # base trip fee
EMERGENCY_SURCHARGE_CENTS = 15000   # surcharge for EMERGENCY jobs
TAX_RATE = 0.0825                   # tax on taxable material base

# Warranty window (PRD §3.7): 30 days.
WARRANTY_DAYS = 30

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

THRESHOLDS = {
    "DEFAULT_HOURLY_RATE_CENTS": DEFAULT_HOURLY_RATE_CENTS,
    "DISPATCH_FEE_CENTS": DISPATCH_FEE_CENTS,
    "EMERGENCY_SURCHARGE_CENTS": EMERGENCY_SURCHARGE_CENTS,
    "TAX_RATE": TAX_RATE,
    "WARRANTY_DAYS": WARRANTY_DAYS,
}
