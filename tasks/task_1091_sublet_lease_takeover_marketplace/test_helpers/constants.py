"""Domain thresholds — numeric constants from the PRD calculations."""

THRESHOLDS = {
    "MAX_RENT_INCOME_RATIO": 0.35,   # STANDARD screening: PASS iff affordability_ratio <= 0.35
    "INCOME_MULTIPLE": 40,           # STRICT screening: PASS iff income_multiple >= 40
    "DEPOSIT_CAP_MULTIPLE": 2,       # deposit capped at 2 * base monthly rent
    "SERVICE_RATE": 0.10,            # platform fee service component on prorated first rent
    "PROCESSING_RATE": 0.03,         # platform fee processing component on deposit
    "HANDOFF_BUFFER_MINUTES": 120,   # landlord-calendar appointment buffer
}

# Server startup default for the logical clock (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
