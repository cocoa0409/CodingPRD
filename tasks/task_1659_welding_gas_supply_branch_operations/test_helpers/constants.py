"""Domain thresholds and rate constants from PRD §2.4, §3.3, §3.6, §3.8."""

# Logical clock (PRD §2.4): startup default before any set call.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Order fees (PRD §3.3)
DELIVERY_FEE_CENTS = 2500
FREE_DELIVERY_THRESHOLD_CENTS = 20000
HAZMAT_FEE_CENTS = 1500

# Rental accrual (PRD §3.6)
DEMURRAGE_MONTHLY_CENTS = 1200
DEFAULT_CYLINDER_GRACE_DAYS = 5
PERIOD_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30, "DEMURRAGE": 30}

# Machine turnaround buffer (PRD §3.6)
MACHINE_TURNAROUND_BUFFER_DAYS = 1

# Training certification validity (PRD §3.8)
CERT_VALIDITY_DAYS = 1095

# Invoice terms (PRD §3.7)
NET30_DUE_DAYS = 30

# Shared test defaults
TEST_DEFAULTS = {
    "HARDGOOD_PRICE_CENTS": 10000,
    "GAS_PRICE_CENTS": 3000,
    "MACHINE_DAILY_CENTS": 5000,
    "MACHINE_WEEKLY_CENTS": 20000,
    "MACHINE_MONTHLY_CENTS": 60000,
    "CLASS_PRICE_CENTS": 9000,
    "ROUTE_CAPACITY_UNITS": 10,
}
