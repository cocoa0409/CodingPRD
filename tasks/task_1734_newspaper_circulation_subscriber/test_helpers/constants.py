"""Domain thresholds and defaults — numeric constants named in PRD prose."""

THRESHOLDS = {
    # PRD §3.1: a charge's due_date is fourteen days after the period start.
    "TERMS_DAYS": 14,
    # PRD §3.2 lapse thresholds (strictly-greater).
    "GRACE_DAYS": 7,
    "SUSPEND_DAYS": 21,
    "LAPSE_DAYS": 45,
    # PRD §3.4 caps.
    "MONTHLY_GOODWILL_CAP_CENTS": 5000,
    "COMPLAINT_CREDIT_CAP_CENTS": 2000,
    # PRD §3.3: hold length 1..21 days; annual budget 30 days.
    "HOLD_MAX_DAYS": 21,
    "ANNUAL_HOLD_BUDGET_DAYS": 30,
    # PRD §3.5: cancel-flow offer shape.
    "CANCEL_FLOW_DISCOUNT_PCT": 0.25,
    "CANCEL_FLOW_DURATION_WEEKS": 8,
    "OFFER_EXPIRY_DAYS": 7,
    # PRD §3.7 carrier settlement constants.
    "BONUS_PCT": 0.05,
    "BONUS_MAX_COMPLAINTS": 2,
    "PER_COMPLAINT_DEDUCTION_CENTS": 150,
    "DEDUCTION_CAP_CENTS": 3000,
    # PRD §3.9 rack variance tolerance.
    "VARIANCE_TOLERANCE": 2,
    # PRD §3.5 manual offer bounds.
    "MIN_DISCOUNT_PCT": 0.10,
    "MAX_DISCOUNT_PCT": 0.50,
    "MIN_DURATION_WEEKS": 4,
    "MAX_DURATION_WEEKS": 26,
    # PRD §2.5: startup default logical clock.
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "BASE_WEEKLY_RATE_CENTS": 600,
    "PER_COPY_RATE_CENTS": 50,
    "PRICE_PER_COPY_CENTS": 150,
    "MAX_STOPS": 10,
}
