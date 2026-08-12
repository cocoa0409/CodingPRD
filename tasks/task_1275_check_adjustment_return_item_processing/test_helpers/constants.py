"""Domain thresholds and constants named in the PRD (§2.4, §3.1-§3.9)."""

# Logical clock startup default (PRD §2.4): Friday 2026-05-01T00:00:00Z.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Large-item classification: amount_cents >= 500000 is a large item (§3.2).
    "LARGE_ITEM_THRESHOLD_CENTS": 500000,
    # Image-quality defect floor: score below 60 opens an IMAGE_WARRANTY case (§3.3).
    "IMAGE_QUALITY_MIN_SCORE": 60,
    # Auto large-item hold length in business days (§3.2).
    "AUTO_HOLD_BUSINESS_DAYS": 2,
    # Total presentments allowed per item (§3.4).
    "MAX_PRESENTMENTS": 2,
    # CustomerService fee-waive cap in cents (§3.7).
    "FEE_WAIVE_CAP_CENTS": 2500,
    # Reg CC provisional principal cap in cents (§3.8).
    "RECREDIT_PROVISIONAL_CAP_CENTS": 250000,
    # Reg CC windows (§3.8).
    "RECREDIT_FINALIZE_WINDOW_DAYS": 45,
    "RECREDIT_CLAIM_WINDOW_DAYS": 40,
    "RECREDIT_PROVISIONAL_BUSINESS_DAYS": 2,
    # Claim aging thresholds (§3.6, §3.9).
    "CLAIM_ESCALATION_BUSINESS_DAYS": 10,
    "WRITE_OFF_BUSINESS_DAYS": 30,
    # Notification delivery deadline in business days (§3.7).
    "NOTIFICATION_DUE_BUSINESS_DAYS": 1,
    # Return-fee prior-return window (§3.4).
    "RETURN_COUNT_WINDOW_DAYS": 30,
    "SURCHARGE_TIER_1_2_CENTS": 500,
    "SURCHARGE_TIER_3PLUS_CENTS": 1500,
}

# Return-item fee base amounts by reason code (§3.4).
BASE_FEE_CENTS = {
    "NSF": 2500,
    "STOP_PAYMENT": 0,
    "CLOSED_ACCOUNT": 3000,
    "MISSING_ENDORSEMENT": 0,
    "ALTERED_OR_FICTITIOUS": 0,
    "IMAGE_NONCONFORMING": 0,
    "DUPLICATE_PRESENTMENT": 0,
    "REFER_TO_MAKER": 1500,
}

# Risk-tier fee multipliers (§3.4).
RISK_MULTIPLIER = {
    "STANDARD": 1.0,
    "HIGH_RISK": 1.5,
}

# Reg CC daily interest rate applied per elapsed calendar day (§3.8).
DAILY_INTEREST_RATE = 0.0002

TEST_DEFAULTS = {
    "CLAIM_WINDOW_BUSINESS_DAYS": 3,
    "WARRANTY_WINDOW_DAYS": 7,
    "DAILY_CLAIM_CAPACITY": 10,
}
