"""Domain thresholds and shared constants from the PRD (§2.4, §2.8, §3.5, §3.9)."""

# Logical clock reading at server startup (PRD §2.4).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Standard rate schedule reused across scenarios ("card A" rates).
STANDARD_CARD = {
    "storage_method": "DAILY_PRORATED",
    "frozen_storage_cents_per_pallet_month": 3000,
    "chilled_storage_cents_per_pallet_month": 2000,
    "handling_in_cents_per_pallet": 1000,
    "handling_out_cents_per_pallet": 500,
    "blast_base_cents": 2000,
    "blast_per_pallet_cents": 300,
    "liability_model": "LIMITED_LIABILITY",
    "liability_per_pallet_cents": 2000,
    "dwell_exempt": False,
}

# Numeric thresholds named in the PRD.
THRESHOLDS = {
    # Zone posture: tight threshold = max(1, floor(capacity * 0.10)) (§2.8).
    "TIGHT_FRACTION": 0.10,
    # Dwell tiers in whole days -> surcharge percentage of the class rate (§3.9).
    "DWELL_TIER_60_DAYS": 60,
    "DWELL_TIER_90_DAYS": 90,
    "DWELL_TIER_120_DAYS": 120,
    "DWELL_TIER_60_PCT": 0.25,
    "DWELL_TIER_90_PCT": 0.50,
    "DWELL_TIER_120_PCT": 1.00,
    # Dwell zone multipliers (§3.9).
    "FROZEN_ZONE_MULT": 1.0,
    "CHILLED_ZONE_MULT": 1.5,
    # Handling-out volume discount tiers (§3.5).
    "VOLUME_TIER_100_PALLETS": 100,
    "VOLUME_TIER_500_PALLETS": 500,
    "VOLUME_TIER_100_DISCOUNT": 0.10,
    "VOLUME_TIER_500_DISCOUNT": 0.20,
    # Storage proration divisor (§3.9).
    "DAYS_PER_MONTH_DIVISOR": 30,
}

# Default credit limit generous enough to keep fiscal gates out of the way.
DEFAULT_CREDIT_LIMIT = 100_000_000

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
