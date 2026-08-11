"""Domain thresholds and numeric constants from the PRD's business rules.

All values are integer cents / decimal fractions / whole days exactly as the
PRD states them (PRD Sections 2.5, 2.6, 3.1-3.9).
"""

# Logical clock (PRD 2.5): the default logical time before any clock-setting call.
DEFAULT_LOGICAL_NOW = "2026-05-01T00:00:00Z"

# Plan pricing (PRD 3.5): billing-cycle discount locked at subscription creation.
ANNUAL_DISCOUNT_PCT = 0.10
MONTHLY_DISCOUNT_PCT = 0.00

# Referral rewards (PRD 3.9).
REFERRAL_PROVISIONAL_FLAT_CENTS = 2000
REFERRAL_QUALIFIED_SHARE_PCT = 0.20
REFERRAL_QUALIFIED_CAP_CENTS = 5000

# Shipment charge (PRD 3.6): early-season window, charge clamps, size tiers.
EARLY_SEASON_DISCOUNT_PCT = 0.10
EARLY_SEASON_WINDOW_START_MD = "03-01"  # inclusive
EARLY_SEASON_WINDOW_END_MD = "06-01"    # exclusive
MIN_CHARGE_CENTS = 1900
MAX_CHARGE_CENTS = 25000
TIER_T2_MIN_SQM = 500
TIER_T3_MIN_SQM = 2000

# Skip allowance (PRD 3.5): rolling window quota.
MAX_SKIPS_PER_WINDOW = 3
SKIP_WINDOW_DAYS = 365

# Weather gate (PRD 3.7).
RAIN_BLOCK_PCT = 0.40
WIND_BLOCK_KPH = 24
TEMP_LOW_BLOCK_C = 5
TEMP_HIGH_BLOCK_C = 32

# Category buffer (PRD 3.7): default minimum gap between conflicting categories.
DEFAULT_MIN_GAP_DAYS = 14

# Satisfaction claims (PRD 3.9).
CLAIM_WINDOW_DAYS = 30
SATISFACTION_CREDIT_CAP_CENTS = 10000

# Add-on quotes (PRD 3.9): quote lifetime on the logical clock.
QUOTE_EXPIRY_DAYS = 7

# Auto-ship sweep (PRD 2.5): generated box window and next-date advance.
AUTO_SHIP_WINDOW_DAYS = 7
AUTO_SHIP_ADVANCE_DAYS = 90

# Catalog fixture products shared across tests (pricing from the design fixtures).
CATALOG_FIXTURES = {
    "FERT-01": {
        "sku": "FERT-01",
        "name": "Fertilizer",
        "category": "FERTILIZER",
        "list_price_cents": 1200,
        "tier_t1_cents": 800,
        "tier_t2_cents": 700,
        "tier_t3_cents": 600,
        "window_start_md": "03-01",
        "window_end_md": "07-01",
        "conflicting_categories": ["WEED"],
        "min_gap_days": 14,
    },
    "WEED-01": {
        "sku": "WEED-01",
        "name": "Weed control",
        "category": "WEED",
        "list_price_cents": 1500,
        "tier_t1_cents": 1100,
        "tier_t2_cents": 1000,
        "tier_t3_cents": 900,
        "window_start_md": "04-01",
        "window_end_md": "08-01",
        "conflicting_categories": ["FERTILIZER"],
        "min_gap_days": 14,
    },
    "PEST-01": {
        "sku": "PEST-01",
        "name": "Grub control",
        "category": "PEST",
        "list_price_cents": 900,
        "tier_t1_cents": 500,
        "tier_t2_cents": 500,
        "tier_t3_cents": 500,
        "add_on_flat_price_cents": 2500,
        "window_start_md": "05-01",
        "window_end_md": "09-01",
        "conflicting_categories": [],
        "min_gap_days": 14,
    },
    "SEED-A": {
        "sku": "SEED-A",
        "name": "Seed A",
        "category": "SEED",
        "list_price_cents": 400,
        "tier_t1_cents": 333,
        "tier_t2_cents": 333,
        "tier_t3_cents": 333,
        "window_start_md": "03-01",
        "window_end_md": "07-01",
        "conflicting_categories": [],
        "min_gap_days": 14,
    },
    "SEED-B": {
        "sku": "SEED-B",
        "name": "Seed B",
        "category": "SEED",
        "list_price_cents": 600,
        "tier_t1_cents": 555,
        "tier_t2_cents": 555,
        "tier_t3_cents": 555,
        "window_start_md": "03-01",
        "window_end_md": "07-01",
        "conflicting_categories": [],
        "min_gap_days": 14,
    },
}
