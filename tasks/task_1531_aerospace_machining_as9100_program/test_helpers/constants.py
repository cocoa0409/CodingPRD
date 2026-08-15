"""Domain thresholds — numeric constants named in the PRD (§2.5, §3)."""

# Logical clock (PRD §2.5): startup default, never wall-clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Pricing (PRD §3.2)
SPECIAL_PROCESS_SURCHARGE_PCT = 0.10

# Nonconformance costing (PRD §3.7)
LABOR_RATE_CENTS_PER_HOUR = 12500

# SPC capability (PRD §3.6)
SPC_MIN_MEASUREMENTS = 5
SPC_WINDOW = 25
CPK_THRESHOLD = 1.33

# Rate readiness (PRD §3.1)
RATE_READY_MIN = 100
RATE_MARGINAL_MIN = 80
RATE_SUSPEND_AFTER = 2

# Escape reporting (PRD §3.7)
ESCAPE_WINDOW_HOURS = 48

# Delegated inspection authority (PRD §3.8)
DIA_COOLING_OFF_DAYS = 30

THRESHOLDS = {
    "SPC_MIN_MEASUREMENTS": SPC_MIN_MEASUREMENTS,
    "SPC_WINDOW": SPC_WINDOW,
    "CPK_THRESHOLD": CPK_THRESHOLD,
    "RATE_READY_MIN": RATE_READY_MIN,
    "RATE_MARGINAL_MIN": RATE_MARGINAL_MIN,
    "RATE_SUSPEND_AFTER": RATE_SUSPEND_AFTER,
    "ESCAPE_WINDOW_HOURS": ESCAPE_WINDOW_HOURS,
    "DIA_COOLING_OFF_DAYS": DIA_COOLING_OFF_DAYS,
}

# Standard commercial terms reused across tests.
DEFAULT_PRICING_TIERS = [
    {"min_qty": 1, "unit_price_cents": 5000},
    {"min_qty": 100, "unit_price_cents": 4500},
    {"min_qty": 500, "unit_price_cents": 4000},
]
DEFAULT_REBATE_TIERS = [
    {"min_invoiced_cents": 0, "rebate_pct": 0},
    {"min_invoiced_cents": 10000000, "rebate_pct": 0.02},
    {"min_invoiced_cents": 50000000, "rebate_pct": 0.05},
]
DEFAULT_CEILING_CENTS = 100000000
DEFAULT_COMMITTED_RATE = 100
