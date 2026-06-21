"""Domain thresholds — numeric constants from the PRD's calculations (PRD §3.4, §3.5, §2.7)."""

# Wash-sale window day count (PRD §3.5): window is [disposed_at - 30d, disposed_at + 30d] inclusive.
WASH_SALE_DAYS = 30

# Maximum permitted absolute correlation between sold and replacement security (PRD §3.4):
# abs(correlation) must be at most 0.95.
MAX_REPLACEMENT_CORRELATION = 0.95

# Risk-scoring weights (PRD §3.2).
HORIZON_W = 0.35
TOLERANCE_W = 0.35
INCOME_W = 0.20
LIQUIDITY_W = 0.10

# Risk-score clamp bounds (PRD §3.2).
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

THRESHOLDS = {
    "WASH_SALE_DAYS": WASH_SALE_DAYS,
    "MAX_REPLACEMENT_CORRELATION": MAX_REPLACEMENT_CORRELATION,
    "HORIZON_W": HORIZON_W,
    "TOLERANCE_W": TOLERANCE_W,
    "INCOME_W": INCOME_W,
    "LIQUIDITY_W": LIQUIDITY_W,
}

# A standard high-risk questionnaire that scores 82 against an inclusive [70,100] band
# (horizon 30, loss_tolerance 9, liquidity_need 1, income_band 8) — PRD §3.2.
HIGH_RISK_QUESTIONNAIRE = {
    "horizon_years": 30,
    "loss_tolerance": 9,
    "liquidity_need": 1,
    "income_band": 8,
}
