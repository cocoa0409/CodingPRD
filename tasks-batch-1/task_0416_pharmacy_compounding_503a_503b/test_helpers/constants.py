"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

THRESHOLDS = {
    # Beyond-use dating (PRD §3.6)
    "STERILE_AQUEOUS_BUD_DAYS": 14,
    "STERILE_NONAQUEOUS_BUD_DAYS": 45,
    "OFFICE_USE_BUD_CAP_DAYS": 90,
    # Yield reconciliation (PRD §3.6)
    "YIELD_TOLERANCE_PCT": 5.0,
    # Endotoxin route-tiered ceilings (PRD §3.7)
    "INJECTABLE_EU_LIMIT": 175,
    "NONINJECTABLE_EU_LIMIT": 350,
    # Prescription validity (PRD §3.5)
    "PRESCRIPTION_VALIDITY_DAYS": 180,
    # Anticipatory window default (PRD §3.2)
    "DEFAULT_ANTICIPATORY_WINDOW_DAYS": 30,
}

# Deterministic facility clock baseline used across fixtures (PRD §2.4 / §3.1).
DEFAULT_CLOCK = "2026-06-01T00:00:00.000Z"
FACILITY_EPOCH = "1970-01-01T00:00:00.000Z"
FAR_FUTURE_EXPIRY = "2030-01-01T00:00:00.000Z"
