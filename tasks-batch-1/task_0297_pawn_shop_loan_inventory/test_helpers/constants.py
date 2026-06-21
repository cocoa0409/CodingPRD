"""Domain thresholds — numeric constants from the PRD's pricing calculations."""

# Basis-point denominator used across all rate math (PRD §3.x).
BPS_DENOMINATOR = 10000

# Resale markup applied to appraised value when an item is forfeited (PRD §3.7).
RESALE_MARKUP_BPS = 3500

# Layaway deposit rate (PRD §3.9): 2000 bps = 20% of total price.
DEPOSIT_BPS = 2000

# Layaway restocking rate (PRD §3.9): 1000 bps = 10% of total price.
RESTOCKING_BPS = 1000

# A finance period is 30 days (PRD §3.4).
PERIOD_DAYS = 30

# Canonical FL state schedule used by most design fixtures.
FL_SCHEDULE = {
    "state_code": "FL",
    "monthly_interest_bps": 1000,
    "monthly_storage_fee_cents": 500,
    "setup_fee_cents": 200,
    "term_days": 30,
    "grace_days": 30,
    "max_principal_cents": 5_000_000,
    "max_periods_total": 4,
    "loan_to_value_bps": 5000,
    "layaway_buffer_days": 7,
}

# Canonical CA state schedule used by cap / period-cap design fixtures.
CA_SCHEDULE = {
    "state_code": "CA",
    "monthly_interest_bps": 250,
    "monthly_storage_fee_cents": 0,
    "setup_fee_cents": 0,
    "term_days": 120,
    "grace_days": 10,
    "max_principal_cents": 250_000,
    "max_periods_total": 1,
    "loan_to_value_bps": 5000,
    "layaway_buffer_days": 3,
}

# Fixed clock epochs used by the design fixtures.
EPOCH = "2026-01-01T00:00:00.000Z"
DAY_30 = "2026-01-31T00:00:00.000Z"      # origination + 30 days (term_end)
DAY_45 = "2026-02-15T00:00:00.000Z"      # mid-grace
DAY_59 = "2026-03-01T00:00:00.000Z"      # ceil(59/30) = 2 periods
GRACE_END = "2026-03-02T00:00:00.000Z"   # origination + 60 days (grace_end)
