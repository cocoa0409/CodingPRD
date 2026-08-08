"""Domain thresholds and test defaults derived from the PRD calculations."""

# --- Pricing constants (PRD Section 2.5 / 3.1 / 3.4) ---
SELF_PAY_DISCOUNT_PCT = 0.35            # self-pay price = gross * (1 - 0.35) = gross * 0.65
SELF_PAY_KEEP_FRACTION = 0.65

# --- Scheduling (PRD Section 2.9) ---
CLEANUP_BUFFER_MINUTES = 15            # provider bookings buffered by 15 minutes

# --- Logical clock (PRD Section 3.9) ---
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
TEST_CLOCK_UTC = "2026-06-01T00:00:00Z"   # standard clock used before scheduling

# --- Canonical benefit-plan shape used across the pricing scenarios ---
DEFAULT_PLAN = {
    "payer_name": "Acme Health",
    "plan_year": 2026,
    "individual_deductible_cents": 100000,
    "individual_oop_max_cents": 500000,
    "coinsurance_rate": 0.20,
    "copay_cents": 2500,
    "in_network": True,
}

# --- Canonical procedure / rate magnitudes ---
GROSS_CHARGE_CENTS = 300000
FLAT_RATE_CENTS = 200000
SELF_PAY_PRICE_CENTS = 195000          # round_half_up(300000 * 0.65)
