"""Domain thresholds — numeric constants from the PRD's pricing and refund rules."""

# Booth-fee tiered pricing (PRD §3.8).
TIER_RATE = {"STANDARD": 150.00, "PREMIUM": 300.00, "FOOD": 450.00}
ZONE_SURCHARGE = {"A": 0.20, "B": 0.10, "C": 0.00}
POWER_DAILY = 40.00

# Voluntary refund fee-fraction tiers, keyed by whole days before start (PRD §3.5).
VOLUNTARY_FEE_PCT_GE_14 = 0.00
VOLUNTARY_FEE_PCT_7_TO_13 = 0.25
VOLUNTARY_FEE_PCT_1_TO_6 = 0.50
VOLUNTARY_FEE_PCT_LT_1 = 1.00

# Default policy knobs (PRD §3.1).
DEFAULT_MAX_REENTRIES = 1
DEFAULT_WRISTBAND_CASHOUT_PCT = 0.03
DEFAULT_VENDOR_COMMISSION_PCT = 0.08

# Convenience defaults used across fixtures.
TEST_DEFAULTS = {
    "ZONE_SLOT_CAPACITY": 1,
    "STAGE_CHANGEOVER_MINUTES": 30,
    "PARKING_PRICE_PER_PASS": 25.00,
    "CAMPING_PRICE_PER_NIGHT": 30.00,
}
