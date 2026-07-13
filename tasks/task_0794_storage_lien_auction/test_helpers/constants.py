"""Domain thresholds — numeric constants from the PRD's calculations (§2.6, §3)."""

# Lien calculation constants (PRD §3.2).
CURE_DAYS = 14
LATE_FEE_CENTS = 5000
LIEN_ADMIN_FEE_CENTS = 10000

# Sale-charge and deposit constants (PRD §3.4, §3.5).
BUYER_PREMIUM_BPS = 1500
DEPOSIT_REQUIRED_CENTS = 20000

# Sale deadline constants (PRD §3.5).
PAYMENT_WINDOW_HOURS = 48
CLEANOUT_DAYS = 3

# Logical-clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Canonical scenario figures shared across the design indices. All monetary
# values are pre-computed against the PRD formulas for the reference scenario:
#   facility sales_tax_rate_bps=825, facility_fee_bps=1000;
#   unit monthly_rent_cents=30000 (daily_rent=1000), past_due=60000;
#   notice at 2026-03-01, mature at 2026-03-20 (19 elapsed days);
#   winning bid 150000.
CANONICAL = {
    "sales_tax_rate_bps": 825,
    "facility_fee_bps": 1000,
    "monthly_rent_cents": 30000,
    "past_due_balance_cents": 60000,
    "provisional_lien_cents": 89000,   # 60000 + 14*1000 + 5000 + 10000
    "final_lien_cents": 94000,         # 60000 + 19*1000 + 5000 + 10000
    "winning_amount_cents": 150000,
    "buyer_premium_cents": 22500,      # round(150000 * 0.15)
    "sales_tax_cents": 14231,          # round((150000+22500) * 0.0825)
    "total_due_cents": 186731,
    "estimated_surplus_cents": 46000,  # 150000 - 89000 - 15000
    "final_surplus_cents": 41000,      # 150000 - 94000 - 15000
    "lien_recovered_cents": 94000,
    "facility_fee_cents": 15000,       # round(150000 * 0.10)
    "facility_recovery_cents": 131500, # 94000 + 15000 + 22500
    "deposit_funded_cents": 100000,
}

# Reference auction window and clock waypoints for the canonical scenario.
CLOCK_MATURE = "2026-03-20T00:00:00Z"
CLOCK_OPEN = "2026-03-21T01:00:00Z"
CLOCK_CLOSE = "2026-03-22T00:00:00Z"
# Sales close at CLOCK_CLOSE, so their payment_deadline is 48h later (2026-03-24).
# This waypoint sits strictly inside that still-open window.
CLOCK_WITHIN_PAYMENT_WINDOW = "2026-03-23T00:00:00Z"
CLOCK_PAST_PAYMENT_DEADLINE = "2026-03-25T00:00:00Z"
AUCTION_START = "2026-03-21T00:00:00Z"
AUCTION_END = "2026-03-22T00:00:00Z"
