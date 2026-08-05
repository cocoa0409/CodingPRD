"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Tiered self-pay refill charge (PRD §3.6)
REFILL_PRICING = {
    "TIER1_MAX_UNITS": 4,
    "TIER2_MAX_UNITS": 10,
    "TIER2_RATE": 0.90,
    "TIER3_RATE": 0.80,
    "CONTROLLED_SUBSTANCE_SURCHARGE_CENTS": 1500,
    "REFILL_MIN_CHARGE_CENTS": 1000,
    "REFILL_MAX_CHARGE_CENTS": 100000,
}

# Patient monitoring risk scoring (PRD §3.8)
MONITORING_RISK = {
    "HCT_WEIGHT": 8,
    "HCT_BASE": 50,
    "PSA_WEIGHT": 15,
    "PSA_BASE": 3.0,
    "LOW_T_PENALTY": 25,
    "LOW_T_THRESHOLD": 300,
    "MONITORING_WINDOW_DAYS": 90,
}

# Safety thresholds (PRD §3.3, §3.5)
HEMATOCRIT_UNSAFE_THRESHOLD = 54.0
PSA_UNSAFE_THRESHOLD = 4.0

# Telehealth clinician double-booking buffer (PRD §3.4)
TELEHEALTH_BUFFER_MINUTES = 15

# Logical clock startup value (PRD §2.10)
CLOCK_START = "2026-05-01T00:00:00Z"
