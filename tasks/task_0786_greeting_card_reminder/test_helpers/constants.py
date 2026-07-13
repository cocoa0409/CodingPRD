"""Domain thresholds — numeric constants from the PRD's calculations."""

# Postage tier ladder (PRD §3.4): first tier whose weight ceiling the total
# weight does not exceed.
POSTAGE_TIERS = [
    {"max_grams": 30, "cents": 150},
    {"max_grams": 60, "cents": 250},
    {"max_grams": 120, "cents": 450},
    {"max_grams": 2147483647, "cents": 800},
]

# Sales-tax rate by recipient region (PRD §3.6). DEFAULT applies to any region
# not listed.
REGION_TAX_RATES = {
    "CA": 0.0725,
    "NY": 0.08875,
    "TX": 0.0625,
    "WA": 0.065,
    "DEFAULT": 0.0,
}

# Subscription tier table (PRD §3.1).
SUBSCRIPTION_TIERS = {
    "FREE": {"monthly_card_credits": 0, "monthly_fee_cents": 0, "discount_pct": 0.0},
    "PLUS": {"monthly_card_credits": 4, "monthly_fee_cents": 1200, "discount_pct": 0.10},
    "PRO": {"monthly_card_credits": 12, "monthly_fee_cents": 3000, "discount_pct": 0.20},
}

# Subscription billing period length in days (PRD §3.1).
PERIOD_DAYS = 30

# Reminder-window buffer, in days (PRD §3.2).
REMINDER_BUFFER_DAYS = 2

# Default startup value of the logical clock (PRD §2.5).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "SCHEDULED_SEND_AT": "2026-04-01T00:00:00Z",
    "PRODUCE_CLOCK": "2026-04-01T00:00:00Z",
}
