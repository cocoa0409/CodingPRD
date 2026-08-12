"""Domain thresholds and numeric constants from PRD §3."""

# Pick fee (PRD §3.4)
CASE_PICK_FEE_CENTS = 12
SPLIT_PICK_FEE_CENTS = 45

# Minimum-drop fee (PRD §3.4)
MIN_DROP_THRESHOLD_CENTS = 50_000
MIN_DROP_FEE_CENTS = 2_500

# Fuel surcharge tiers on weekly DOE index (PRD §3.5)
FUEL_TIER_LOW_MAX_USD = 3.50      # idx < 3.50 -> 0%
FUEL_TIER_MID_MAX_USD = 4.00      # 3.50 <= idx < 4.00 -> 2.5%
FUEL_RATE_MID = 0.025
FUEL_RATE_HIGH = 0.040

# Slotting fee (PRD §3.8)
SLOT_BASE_CENTS = 50_000
SLOT_PER_UNIT_CENTS = 250
SLOT_CAP_CENTS = 150_000

# Invoice due-date offsets in days (PRD §3.6)
DUE_DATE_OFFSET_NET7 = 7
DUE_DATE_OFFSET_NET14 = 14

# Logical clock startup value (PRD §2.4)
CLOCK_START_ISO = "2026-05-01T00:00:00Z"
