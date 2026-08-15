"""Domain thresholds and constants from the PRD (§2.4, §3.2, §3.5, §3.7, §3.8)."""

THRESHOLDS = {
    # Shipping gate: blocked exposure at or above $100,000.00 blocks ship (PRD §3.5).
    "BLOCK_THRESHOLD_CENTS": 10_000_000,
    # Collection standing renewal window (PRD §3.2).
    "RENEWAL_WINDOW_DAYS": 45,
    # Audit sample documentation response window (PRD §3.8).
    "DOC_RESPONSE_WINDOW_DAYS": 10,
    # FIXED_FLOOR population cap inside the sample-size formula (PRD §3.8).
    "FIXED_FLOOR_POPULATION_CAP": 5,
}

# STATISTICAL sample-size multipliers per target confidence (PRD §3.8).
CONFIDENCE_MULTIPLIERS = {90: 0.10, 95: 0.15, 99: 0.25}

# The tenant logical clock origin: day index 0 == 2026-08-01T00:00:00Z (PRD §2.4).
CLOCK_ORIGIN_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "TENANT_LEGAL_NAME": "T1 Inc",
    "TENANT_HOME_STATE": "NY",
    "REASON_CODE": "RES",
    "REASON_TAX_ENGINE_CODE": "R",
    "SHIP_TO_STATE": "CA",
    "SIGNED_DATE": "2026-01-01",
    "EFFECTIVE_DATE": "2026-01-01",
    "CERT_SIGNED_AT_ORIGIN": "2026-08-01",
    "CERT_EFFECTIVE_AT_ORIGIN": "2026-08-01",
}
