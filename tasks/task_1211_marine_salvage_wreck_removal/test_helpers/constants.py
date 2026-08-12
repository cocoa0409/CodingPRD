"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Provisional award (PRD 3.3): flat 12% of declared value for no-cure-no-pay
    "PROVISIONAL_PCT": 0.12,
    # Security requirement (PRD 3.3): 1.25x provisional (NCNP) / 30% of fixed price
    "SECURITY_MULTIPLIER": 1.25,
    "FIXED_SECURITY_PCT": 0.30,
    # Final award tiered caps (PRD 3.9), in cents
    "T1_CAP": 100_000_000,
    "T2_CAP": 500_000_000,
    # Final award additive multipliers (PRD 3.9)
    "RISK_ADD": {"GROUNDING": 0.05, "COLLISION": 0.08, "FIRE": 0.10, "SUNK": 0.15},
    "ENV_ADD": {"TIER_1": 0.05, "TIER_2": 0.10, "TIER_3": 0.20},
    # Charter cost rate-line factors (PRD 3.6)
    "STANDBY_FACTOR": 0.5,
    "DEMURRAGE_FACTOR": 1.5,
    # Special compensation (PRD 3.7)
    "SCOPIC_UPLIFT_MULT": 1.25,
    "POLLUTANT_MULT": {
        "OIL_PERSISTENT": 1.5,
        "OIL_NON_PERSISTENT": 1.2,
        "CHEMICAL": 1.8,
        "DEBRIS": 1.0,
    },
    # Weather feasibility buffer at both window ends (PRD 3.6)
    "WEATHER_BUFFER_HOURS": 6,
    # Fixed-price overrun threshold factor (PRD 3.6)
    "OVERRUN_FACTOR": 1.10,
    # Doc pack submit completeness gate (PRD 3.9)
    "DOC_COMPLETENESS_REQUIRED_PCT": 100,
}

# Permit agency requirements per phase type (PRD 3.5)
PERMIT_MAP = {
    "MOBILIZATION": ["PORT_AUTHORITY"],
    "LIGHTERING": ["COAST_GUARD", "ENV_AGENCY"],
    "REFLOAT": ["COAST_GUARD"],
    "TOWAGE": ["COAST_GUARD"],
    "WRECK_REMOVAL": ["COAST_GUARD", "ENV_AGENCY"],
    "DEMOBILIZATION": ["PORT_AUTHORITY"],
}

TEST_DEFAULTS = {
    "DECLARED_SALVED_VALUE_CENTS": 200_000_000,
    "DAY_RATE_CENTS": 2_000_000,
    # Logical clock reads exactly this before any client sets it (PRD 2.4)
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
    # Commonly used operation timestamps
    "OPS_START": "2026-05-10T00:00:00Z",
}
