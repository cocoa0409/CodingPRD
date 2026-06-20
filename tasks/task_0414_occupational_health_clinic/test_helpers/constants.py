"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# OSHA recordability (PRD §3.10)
OSHA = {
    "MIN_AWAY_DAYS": 1,
    "MIN_RESTRICTED_DAYS": 1,
}

# Invoice volume-discount tiers keyed on the COUNT of line items (PRD §3.13)
INVOICE_TIERS = {
    "TIER1_MIN": 5,
    "TIER1_RATE": 0.05,
    "TIER2_MIN": 10,
    "TIER2_RATE": 0.10,
}

# Surveillance outcome thresholds (PRD §3.12)
SURVEILLANCE = {
    "STS_THRESHOLD_DB": 10,
    "HALF_MASK_MIN_FF": 100,
    "FULL_FACEPIECE_MIN_FF": 500,
}

# Drug-screen recollection limit (PRD §3.6)
RECOLLECTION_LIMIT = 2

# Common test defaults
TEST_DEFAULTS = {
    "NET_TERMS_DAYS": 30,
    "DEFAULT_CURRENT_DATE": "1970-01-01",
}
