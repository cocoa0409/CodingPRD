"""Domain thresholds and canonical inputs from the PRD calculations."""

# Logical clock startup default (PRD 2.4).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Inspection spacing minimum gap in minutes (PRD 3.4: at least 240 minutes / four hours).
INSPECTION_MIN_GAP_MINUTES = 240

# Minimum photos required to submit a report (PRD 3.5).
MIN_PHOTOS = 1

# Catastrophe perils that trigger the fee-schedule CAT multiplier (PRD 3.6).
CAT_PERILS = ["HURRICANE", "FLOOD", "WILDFIRE", "TORNADO"]
NON_CAT_PERILS = ["HAIL", "WIND", "FIRE", "WATER"]

# Canonical fee schedule rate card used across billing tests.
CANONICAL_FEE_SCHEDULE = {
    "name": "STD",
    "tier1_max_rcv_cents": 5_000_000,
    "tier2_max_rcv_cents": 25_000_000,
    "tier1_flat_fee_cents": 30_000,
    "tier2_flat_fee_cents": 60_000,
    "tier3_flat_fee_cents": 100_000,
    "rcv_pct_bps": 250,
    "pct_cap_cents": 20_000_000,
    "hourly_rate_cents": 8_500,
    "cat_peril_multiplier_bps": 12_500,
}

# Standard license validity window (issued before, expires after the default clock).
LICENSE_ISSUED_AT = "2026-01-01T00:00:00Z"
LICENSE_EXPIRES_AT = "2027-01-01T00:00:00Z"
