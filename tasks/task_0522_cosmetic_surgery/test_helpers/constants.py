"""Domain thresholds — numeric constants from PRD calculations."""

# Multi-procedure discount tiers (keyed on line-item count)
DISCOUNT = {
    "TIER2_PCT": 0.05,   # exactly 2 lines
    "TIER3_PCT": 0.10,   # 3 or more lines
    "NONE_PCT": 0.00,    # 1 line
}

DEPOSIT_PCT = 0.20  # required_deposit = 20% of total

# Cancellation notice-window refund tiers
CANCELLATION = {
    "FULL_REFUND_DAYS": 30,   # >= 30 days -> 100%
    "HALF_REFUND_DAYS": 14,   # >= 14 and < 30 -> 50%
    "HALF_REFUND_PCT": 0.50,
}

# Lender merchant discount fees
FINANCING_FEE_PCT = {
    "CHERRY": 0.05,
    "CARECREDIT": 0.03,
}

# Revision charge (out-of-policy)
REVISION_RATE = 0.50

# Surgical risk score weights
RISK = {
    "ASA_STEP": 25,
    "BMI30_PENALTY": 10,
    "BMI35_PENALTY": 20,
    "SMOKER_PENALTY": 20,
    "AGE50_PENALTY": 8,
    "AGE65_PENALTY": 15,
    "PRIOR_PENALTY": 15,
    "STANDARD_THRESHOLD": 40,
    "MEDICAL_THRESHOLD": 70,
}

SURGEON_BUFFER_MINUTES = 60

# Logical clock default at server startup
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Canonical fixture procedure fee literals
PROC_A = {"code": "RHINO01", "name": "Rhinoplasty",
          "surgical_fee_cents": 500000, "facility_fee_cents": 200000,
          "anesthesia_fee_cents": 150000}  # bundle 850000
PROC_B = {"code": "LIPO01", "name": "Liposuction",
          "surgical_fee_cents": 300000, "facility_fee_cents": 150000,
          "anesthesia_fee_cents": 100000}  # bundle 550000
