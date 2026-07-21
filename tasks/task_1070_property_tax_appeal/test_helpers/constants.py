"""Domain thresholds — numeric constants and defaults from the PRD calculations and setup rules."""

# Logical-clock startup default (PRD §2.6).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

# FeeAgreement default contingency structure (PRD §3.1 / §3.4).
FEE_DEFAULTS = {
    "contingency_tier1_pct": 0.40,
    "contingency_tier2_pct": 0.33,
    "contingency_tier3_pct": 0.25,
    "tier1_ceiling_cents": 50000,
    "tier2_ceiling_cents": 150000,
    "minimum_fee_cents": 15000,
}

# Jurisdiction defaults (PRD §3.1).
JURISDICTION_DEFAULTS = {
    "informal_review_available": True,
    "hearing_room_capacity": 3,
    "rep_travel_buffer_minutes": 60,
}

# Common assessment shape reused across design recipes.
TEST_DEFAULTS = {
    "original_assessed_value_cents": 30000000,
    "millage_rate": 25.0,
    "notice_date": "2026-06-15T00:00:00Z",
    "filing_window_days": 60,
    "equalization_ratio": 0.90,
    "tax_year": 2026,
}
