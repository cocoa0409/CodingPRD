"""Domain thresholds — numeric constants from the PRD's fee and workflow rules."""

# Service-fee composition (PRD §3.5).
SERVICE_FEE = {
    "BASE_SERVICE_FEE_CENTS": 4500,
    "EXPEDITE_SURCHARGE_CENTS": 6000,
    "REWORK_SURCHARGE_CENTS": 2500,
}

# Fleet volume-discount tiers in basis points, keyed on ytd_completed_count (PRD §3.6).
FLEET_TIERS = {
    "TIER1_MIN": 5,
    "TIER1_BPS": 625,
    "TIER2_MIN": 20,
    "TIER2_BPS": 1250,
    "TIER3_MIN": 50,
    "TIER3_BPS": 1875,
}

# Workflow caps and windows.
MAX_REJECTION_ROUNDS = 3
EXPEDITE_SLA_HOURS = 48

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"

# A canonical 17-character VIN used across fixtures/tests.
VALID_VIN = "1HGCM82633A004352"
VALID_VIN_2 = "2HGCM82633A004353"
