"""Domain thresholds — numeric constants from the PRD's calculations and business rules."""

# Screening list prices per modality (§3.7)
MODALITY_PRICE_CENTS = {
    "MAMMOGRAPHY": 20000,
    "BLOOD_PANEL": 8000,
    "BONE_DENSITY": 12000,
    "SKIN": 6000,
}

# Provisional coinsurance estimate for INSURANCE charges (§3.7)
INSURANCE_ESTIMATE_COINSURANCE = 0.20

# No-show strike limit that flips a participant to BLOCKED (§3.3)
NO_SHOW_STRIKE_LIMIT = 3

# Grant depletion floor: is_depleted true when remaining_cents <= this (§2.8)
DEPLETION_FLOOR_CENTS = 0

# Referral SLA days by priority (§3.6)
URGENT_SLA_DAYS = 7
ROUTINE_SLA_DAYS = 30

# Logical clock startup default (§2.6)
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
