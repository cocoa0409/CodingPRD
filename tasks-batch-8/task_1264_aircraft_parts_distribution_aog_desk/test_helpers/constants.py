"""Domain thresholds — numeric constants pinned by PRD §2/§3."""

# Logical clock startup default (PRD §2.10)
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Quote validity caps per tier in hours (PRD §3.4)
    "VALIDITY_CAP_STANDARD": 24,
    "VALIDITY_CAP_PRIORITY": 48,
    "VALIDITY_CAP_PLATINUM": 72,
    # Handling-fee brackets on the pre-fee subtotal (PRD §3.4)
    "HANDLING_BRACKET_1_MAX": 100_000,
    "HANDLING_BRACKET_2_MAX": 1_000_000,
    "HANDLING_FEE_SMALL": 9_500,
    "HANDLING_FEE_MID": 4_500,
    # Freight constants (PRD §3.4)
    "FREIGHT_RATE_TIER1": 1_200,   # <= 5 kg
    "FREIGHT_RATE_TIER2": 900,     # 5 < w <= 20 kg
    "FREIGHT_RATE_TIER3": 650,     # 20 < w <= 100 kg
    "FREIGHT_RATE_TIER4": 480,     # > 100 kg
    "DIST_MULT_NEAR": 1.0,         # < 1000 km
    "DIST_MULT_MID": 1.35,         # 1000..4000 km
    "DIST_MULT_FAR": 1.8,          # > 4000 km
    "HOT_SHOT_PREMIUM": 250_000,
    "CHARTER_MIN": 750_000,
    "CHARTER_PER_KM": 2_900,
    "HAZMAT_MULT": 1.25,
    "ESCALATION_MULT": 1.25,
    # Core-return penalty (PRD §3.6)
    "CORE_LATE_FEE": 25_000,
    "CORE_TIER1_DAYS": 7,
    "CORE_TIER2_DAYS": 21,
    "CORE_RETURN_DUE_DAYS": 21,
    # Loan settlement (PRD §3.7)
    "LEASE_PERIOD_DAYS": 30,
    "LOAN_LATE_MULT": 1.5,
    # Priority tier windows (PRD §3.9)
    "TIER_WINDOW_DAYS": 180,
    "PLATINUM_MIN_COUNT": 2,
    "PLATINUM_MIN_RATE": 0.95,
    "PRIORITY_MIN_COUNT": 1,
    "PRIORITY_MIN_RATE": 0.90,
    # Charter turnaround buffer minutes (PRD §3.5)
    "CHARTER_BUFFER_MINUTES": 120,
    # Return window days (PRD §3.8)
    "RETURN_WINDOW_DAYS": 30,
}

TIER_FEE_PCT = {
    "STANDARD": 0.06,
    "PRIORITY": 0.03,
    "PLATINUM": 0.0,
}

# Denied export destinations (PRD §2.8)
DENIED_DESTINATIONS = ("KP", "CU", "IR", "SY")

TEST_DEFAULTS = {
    "CREDIT_LIMIT": 100_000_000,
    "NEEDED_BY": "2026-06-01T00:00:00Z",
}
