"""Domain thresholds — numeric constants from the PRD calculations and defaults."""

# IBNR developed-basis tail (PRD §3.9: developed outstanding floored at 15% of paid total).
IBNR_TAIL_PCT = 0.15

# Vendor invoice tiered hourly rates in cents/hour (PRD §3.6).
VENDOR_HOURLY_RATE_CENTS = {
    "INDEPENDENT_ADJUSTER": 12000,
    "APPRAISER": 15000,
    "CONTRACTOR": 0,
    "DEFENSE_ATTORNEY": 35000,
}

# Vendor invoice line-item constants (PRD §3.6).
MILEAGE_RATE_CENTS = 55
MIN_INVOICE_CENTS = 5000
VENDOR_INVOICE_CAP_CENTS = 2000000

# Adjuster inspection-window travel buffer in minutes (PRD §3.3).
ADJUSTER_TRAVEL_BUFFER_MINUTES = 60

# Field defaults (PRD §3.1).
DEFAULT_SLA_ACK_HOURS = 24
DEFAULT_SLA_CONTACT_HOURS = 72
DEFAULT_DEDUCTIBLE_CENTS = 0
DEFAULT_MAX_OPEN_CLAIMS = 50

# The logical clock's default instant before any client sets it (PRD §2.4).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Convenient generous defaults used by fixtures.
TEST_DEFAULTS = {
    "RESERVE_AUTHORITY_DEFAULT_CENTS": 100000000,
    "ADJUSTER_AUTHORITY_LIMIT_CENTS": 5000000,
    "COVERAGE_LIMIT_CENTS": 100000000,
    "PER_CLAIM_EXPENSE_LIMIT_CENTS": 5000000,
    "EFFECTIVE_DATE": "2020-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2030-01-01T00:00:00Z",
    "LOSS_DATE": "2026-06-01T00:00:00Z",
    "REPORTED_DATE": "2026-06-15T00:00:00Z",
}
