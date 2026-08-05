"""Domain thresholds and numeric constants from the PRD calculations."""

# Prior-risk scoring (PRD section 3.4)
PRIOR_RISK = {
    "POP_BASELINE": 0.05,
    "PER_UNIT": 0.05,
    "ASHKENAZI_BONUS": 0.10,
    "RISK_CAP": 0.99,
}

# Residual-risk projection (PRD section 3.6)
RESIDUAL_RISK = {
    "POP_BASELINE": 0.05,
    "UNINFORMATIVE_FACTOR": 0.5,
    "CONFIRMED_CARRIER": 0.99,
}

# Risk tier thresholds (PRD section 3.6; high boundary inclusive)
RISK_TIER = {
    "HIGH_THRESHOLD": 0.20,
    "MODERATE_THRESHOLD": 0.10,
}

# Cascade invitation outreach price sheet (PRD section 3.7)
CASCADE_COST = {
    "LETTER_BASE": 500,
    "EMAIL_BASE": 100,
    "PHONE_BASE": 800,
    "DEGREE1_SURCHARGE": 0,
    "DEGREE2_SURCHARGE": 200,
    "DEGREE3_SURCHARGE": 400,
}

# Screening interval by tier (PRD sections 3.6 / 3.9)
SCREENING_INTERVAL_MONTHS = {
    "HIGH": 6,
    "MODERATE": 12,
    "LOW": 24,
}

# Logical clock (PRD section 2.12)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
