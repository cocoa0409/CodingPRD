"""Domain thresholds — numeric constants drawn from the PRD calculations."""

# Severity classification inclusive upper bounds (dB HL), PRD Section 3.2 / 2.9.
SEVERITY_THRESHOLDS = {
    "NORMAL_MAX_DB": 25,
    "MILD_MAX_DB": 40,
    "MODERATE_MAX_DB": 55,
    "SEVERE_MAX_DB": 70,
    # 71..120 -> PROFOUND
}

# Warranty settlement, PRD Section 3.8.
WARRANTY = {
    "DAMAGE_DEDUCTIBLE_PCT": 0.25,
    "LOSS_DEDUCTIBLE_PCT": 0.50,
    "DEDUCTIBLE_CAP_CENTS": 40000,
}

# Supply cycle loyalty discount, PRD Section 3.9.
SUPPLY = {
    "LOYALTY_THRESHOLD_CYCLES": 6,   # discount applies strictly after cycle 6
    "LOYALTY_DISCOUNT_PCT": 0.10,
}

# Trial window, PRD Section 3.3 (fixed 30-day window).
TRIAL_PERIOD_DAYS = 30

# Clock anchors reused across fixtures.
CLOCK_BASE = "2026-03-01T00:00:00Z"          # before any trial deadline
CLOCK_AFTER_TRIAL = "2026-05-01T00:00:00Z"   # past the 30-day trial window
