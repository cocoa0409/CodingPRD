"""Domain thresholds — numeric constants from PRD calculations and rules."""

THRESHOLDS = {
    # Pitot / fire-flow formula (PRD §3.3)
    "PITOT_K": 29.83,
    "EXTRAPOLATION_EXPONENT": 0.54,
    "REFERENCE_RESIDUAL_PSI": 20,
    # Dechlorination protocol (PRD §3.4)
    "DISCHARGE_LIMIT_MG_L": 0.1,
    "LITERS_PER_GALLON": 3.785,
    "TABLET_NEUTRALIZES_MG": 8500,
    # Inspection due tiers (PRD §3.9)
    "MUNICIPAL_CYCLE_MONTHS": 12,
    "PRIVATE_CYCLE_MONTHS": 6,
    "DUE_SOON_DAYS": 30,
    "CRITICAL_DAYS": 90,
    # Complaint cluster (PRD §3.5)
    "CLUSTER_THRESHOLD": 3,
    "CLUSTER_WINDOW_HOURS": 72,
    "AUTO_SEQUENCE_DELAY_HOURS": 24,
    "AUTO_SEQUENCE_DURATION_HOURS": 4,
    # Outage notification handshake (PRD §3.6)
    "ACK_DEADLINE_HOURS": 2,
    # Work-order tiered pricing (PRD §3.7)
    "DISCOUNT_TIER1_CENTS": 20000,
    "DISCOUNT_TIER1_PCT": 0.05,
    "DISCOUNT_TIER2_CENTS": 100000,
    "DISCOUNT_TIER2_PCT": 0.10,
    "HANDLING_FEE_THRESHOLD_CENTS": 25000,
    "HANDLING_FEE_CENTS": 1500,
    # ISO scoring (PRD §3.8)
    "FLOW_WEIGHT": 0.6,
    "INSPECTION_WEIGHT": 0.4,
    "ISO_FLOW_LOOKBACK_MONTHS": 60,
    "PRIVATE_WEIGHT": 0.5,
    # Zone default (PRD §3.1)
    "DEFAULT_COOLDOWN_MINUTES": 60,
}

TEST_DEFAULTS = {
    # Logical clock initial reading (PRD §2.8)
    "CLOCK_INITIAL": "2026-08-01T00:00:00Z",
    "PROGRAM_YEAR": 2026,
    "SEASON": "SPRING",
    "REQUIRED_FIRE_FLOW_GPM": 1000,
    "OUTLET_DIAMETER_IN": 2.5,
    "DISCHARGE_COEFFICIENT": 0.9,
    # Standard valid results payload: static 80 / residual 40 / pitot 64
    # yields pitot_flow_gpm 1342.35 and flow_at_20psi_gpm 1671 (PRD §3.3).
    "STATIC_PSI": 80,
    "RESIDUAL_PSI": 40,
    "PITOT_PSI": 64,
    "EXPECTED_PITOT_FLOW_GPM": 1342.35,
    "EXPECTED_FLOW_AT_20PSI_GPM": 1671,
}
