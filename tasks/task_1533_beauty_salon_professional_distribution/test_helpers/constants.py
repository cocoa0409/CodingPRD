"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Tier evaluation (PRD §3.3)
    "GOLD_FLOOR_CENTS": 2000000,
    "PLATINUM_FLOOR_CENTS": 5000000,
    "TIER_WINDOW_DAYS": 365,
    # Credit redemption (PRD §3.5)
    "POINT_VALUE_CENTS": 100,
    # Education-credit accrual (PRD §3.9)
    "ACCRUAL_DIVISOR_CENTS": 1000,
    # Backbar quota (PRD §3.6)
    "BACKBAR_RATIO": 2.0,
    "BACKBAR_WINDOW_DAYS": 90,
    # Route stop buffer (PRD §3.10)
    "ROUTE_STOP_BUFFER_MINUTES": 30,
    # Liquidation ladder (PRD §3.4)
    "LIQ_STEP_DAYS": 14,
    # Hazmat shipping (PRD §3.7)
    "HAZMAT_FLAT_CENTS": 2500,
    "HAZMAT_PER_GRAM_CENTS": 2,
    # Consultant commission, accelerator variant (PRD §3.10)
    "ACC_T1_CENTS": 1000000,
    "ACC_T2_CENTS": 3000000,
    # Diversion (PRD §3.11)
    "DIVERSION_SUSPENSION_STRIKES": 3,
    "RISK_SCORE_CAP": 100,
}

TIER_DISCOUNT = {"SILVER": 0.0, "GOLD": 0.10, "PLATINUM": 0.15}
BACKBAR_DISCOUNT = 0.20
TIER_MULTIPLIER = {"SILVER": 1, "GOLD": 2, "PLATINUM": 3}
METHOD_BASE_CENTS = {"GROUND": 1200, "AIR": 3000}
STRAIGHT_RATE = 0.05
ACC_RATES = (0.04, 0.06, 0.08)
CREDIT_CAP_RATIO = 0.5

TEST_DEFAULTS = {
    "TERRITORY": "CA",
    "LICENSE_VALID_UNTIL": "2027-06-01T00:00:00Z",
    "PROMO_STARTS_AT": "2026-07-01T00:00:00Z",
    "PROMO_ENDS_AT": "2027-01-01T00:00:00Z",
    "BASE_PRICE_CENTS": 10000,
    "WEIGHT_GRAMS": 100,
}
