"""Domain thresholds — numeric constants stated in the PRD."""

# PRD §3.9 — per-gallon IFTA tax rates, in cents.
TAX_RATE_CENTS = {
    "CA": 68,
    "AZ": 26,
    "NV": 33,
    "OR": 38,
    "TX": 20,
}

# PRD §3.5 — the default rebate schedule: 5 cpg from 0 gallons, 8 cpg once
# month-to-date reaches 1000 gallons, 12 cpg once it reaches 5000 gallons.
DEFAULT_REBATE_TIERS = [
    {"min_month_gallons": 0, "cpg_rebate": 5},
    {"min_month_gallons": 1000, "cpg_rebate": 8},
    {"min_month_gallons": 5000, "cpg_rebate": 12},
]

# PRD §3.7 — the maintenance buffer applied to both sides of a critical
# fault's window when checking for collisions.
MAINTENANCE_BUFFER_HOURS = 2

# PRD §2.4 — the logical clock's value before any call is made.
CLOCK_DEFAULT_AT_STARTUP = "2026-05-01T00:00:00Z"

# PRD §2.3 — pagination defaults.
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# A syntactically well-formed UUID that never identifies a persisted resource.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# Convenient roomy defaults so that a fixture only constrains the control under test.
TEST_DEFAULTS = {
    "CLOCK": "2026-06-01T12:00:00Z",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "DAILY_LIMIT_CENTS": 100_000_000,
    "PER_TXN_GALLON_LIMIT": 2000,
    "TANK_CAPACITY_GALLONS": 5000,
    "UNIT_PRICE_CENTS": 400,
    "EFFECTIVE_FROM": "2026-06-01T00:00:00Z",
}
