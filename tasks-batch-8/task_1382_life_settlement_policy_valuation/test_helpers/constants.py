"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

THRESHOLDS = {
    # Screening minimums (PRD §3.1)
    "MIN_FACE_CENTS": 10000000,
    "MIN_AGE_YEARS": 65,
    "CONTESTABILITY_MONTHS": 24,
    # Reserve pricing (PRD §3.2)
    "PRICING_RATE_BPS": 1300,
    "EXPENSE_FLAT_CENTS": 250000,
    "EXPENSE_FACE_BPS": 150,
    "PRICE_CAP_FACE_BPS": 8000,
    # LE blend tier weights (PRD §3.2)
    "TIER_WEIGHT_A": 3,
    "TIER_WEIGHT_B": 1,
    # Escrow waterfall (PRD §3.5)
    "ESCROW_FEE_CENTS": 75000,
    "SERVICING_FEE_BPS": 25,
    "COMMISSION_CAP_BPS": 600,
    "COMMISSION_CAP_FACE_BPS": 600,
    # Rescission window (PRD §3.5)
    "RESCISSION_WINDOW_DAYS": 15,
    # Negotiation (PRD §3.3)
    "MAX_NEGOTIATION_ROUND": 4,
    "OFFER_EXPIRES_DEFAULT_DAYS": 10,
    "OFFER_EXPIRES_MAX_DAYS": 30,
    # Marketing deadline (PRD §3.2)
    "MARKETING_DEADLINE_DAYS": 90,
    # LE report validity (PRD §3.2)
    "LE_VALID_DAYS": 180,
    # Premium payments (PRD §3.7)
    "PAYMENT_INTERVAL_DAYS": 30,
    "GRACE_DAYS": 31,
    "MAX_PAYMENT_ROWS": 360,
    "LAPSE_MISS_COUNT": 2,
    # Tracking verification currency (PRD §3.8)
    "COVERAGE_WINDOW_DAYS": 90,
    # Closing approval license horizon (PRD §3.4)
    "LICENSE_EXPIRY_HORIZON_DAYS": 30,
    # Startup default logical clock (PRD §2.4)
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "FACE": 10000000,
    "ANNUAL_PREMIUM": 600000,
    "OFFER_AMOUNT": 6000000,
    "COMMISSION_BPS": 455,
    "EXPECTED_FUNDING": 6090000,  # 6000000 + 75000 + round_half_up(6000000*25/10000)
}
