"""Domain thresholds — numeric constants from the Mold Remediation PRD calculations."""

# Logical clock: startup default and the standard test instant used by setups.
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"
TEST_CLOCK = "2026-01-15T00:00:00Z"

THRESHOLDS = {
    # NESHAP applicability (PRD §3.2)
    "NESHAP_SQFT_THRESHOLD": 160,        # >= triggers NESHAP for ASBESTOS
    "NESHAP_NOTICE_DAYS": 10,            # minimum NESHAP lead, whole days
    "SECONDS_PER_DAY": 86400,
    # Containment (PRD §3.4)
    "MIN_NEGATIVE_PRESSURE_PA": 5,       # absolute floor any zone may require
    # Worker eligibility (PRD §3.1)
    "PPE_FIT_VALID_DAYS": 365,
    # Sample grade tiers — AIR spores/m3 (PRD §3.3)
    "AIR_ELEVATED": 1000,
    "AIR_HAZARD": 10000,
    # Sample grade tiers — SURFACE raw count (PRD §3.3)
    "SURFACE_ELEVATED": 50,
    "SURFACE_HAZARD": 500,
    "LITERS_PER_M3": 1000,
    # Clearance limits, spores/m3, hazard-specific (PRD §3.8)
    "ASBESTOS_LIMIT": 70,
    "LEAD_LIMIT": 200,
    "MOLD_LIMIT": 900,
    # Disposal fee tiers (PRD §3.6)
    "TIER1_KG": 100,
    "TIER2_KG": 500,
    "RATE1_CPK": 80,
    "RATE2_CPK": 120,
    "RATE3_CPK": 200,
    "ASBESTOS_SURCHARGE": 1.5,
    "LEAD_SURCHARGE": 1.25,
    "MOLD_SURCHARGE": 1.0,
    # Insurance labor rate (PRD §3.9)
    "LABOR_CPK": 1500,                   # cents per kg
}

TEST_DEFAULTS = {
    "STRUCTURE_SQFT": 80,
    "JURISDICTION_CODE": "US-EPA",
    "REQUIRED_PRESSURE_PA": 10,
    "COMPLIANT_READING_PA": 12,
    "HAULER_NAME": "Acme",
    "CERT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "PPE_FIT_TEST_AT": "2025-12-15T00:00:00Z",
    "PAST_READING_AT": "2026-01-14T00:00:00Z",
    "PAST_COLLECTED_AT": "2026-01-14T00:00:00Z",
    "SHIFT_START_AT": "2026-01-15T08:00:00Z",
    "SHIFT_END_AT": "2026-01-15T16:00:00Z",
}
