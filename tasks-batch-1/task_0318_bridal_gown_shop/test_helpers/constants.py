"""Domain thresholds — numeric constants from the PRD's pricing and ledger rules (§3)."""

# Gown order pricing (§3.3, §3.4)
SIZE_UPCHARGE_FLOOR = 20      # ordered_size >= 20 carries a plus-size upcharge
SIZE_UPCHARGE_PCT = 0.15      # 15% of base_price_cents, rounded up
RUSH_SURCHARGE_PCT = 0.30     # 30% of base_price_cents, rounded up

# Alteration cost (§3.5)
LABOR_RATE_CENTS_PER_MIN = 120
REFIT_SURCHARGE_PCT = 0.10    # +10% per refitting round

# Payment plan (§3.6)
DEPOSIT_FLOOR_PCT = 0.50      # minimum deposit = ceil(plan_total_cents * 0.50)

THRESHOLDS = {
    "SIZE_UPCHARGE_FLOOR": SIZE_UPCHARGE_FLOOR,
    "SIZE_UPCHARGE_PCT": SIZE_UPCHARGE_PCT,
    "RUSH_SURCHARGE_PCT": RUSH_SURCHARGE_PCT,
    "LABOR_RATE_CENTS_PER_MIN": LABOR_RATE_CENTS_PER_MIN,
    "REFIT_SURCHARGE_PCT": REFIT_SURCHARGE_PCT,
    "DEPOSIT_FLOOR_PCT": DEPOSIT_FLOOR_PCT,
}

# Convenient default order shapes reused across fixtures/tests.
TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 180000,
    "STANDARD_LEAD_DAYS": 60,
    "ORDERED_SIZE": 10,
}
