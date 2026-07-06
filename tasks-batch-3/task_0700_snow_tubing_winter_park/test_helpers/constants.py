"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Default logical clock (PRD §2.11): before any clock call the clock reads this.
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Park safety threshold defaults (PRD §2.6 / §3.1).
DEFAULT_MIN_SNOW_DEPTH_CM = 15
DEFAULT_MAX_SAFE_WIND_KPH = 50

# Ticket pricing base tiers in cents (PRD §3.4).
CHILD_CENTS = 1500       # age < 6
JUNIOR_CENTS = 2500      # 6 <= age < 13
SENIOR_CENTS = 2000      # age >= 65
ADULT_CENTS = 3500       # 13 <= age <= 64

# Pass discounts (PRD §3.4).
SILVER_DISCOUNT = 0.10
GOLD_DISCOUNT = 0.25
RESIDENT_GOLD_DISCOUNT = 0.40
RESIDENT_DISCOUNT = 0.05

# Season pass daily redemption allowances by tier (PRD §3.3).
PASS_DAILY_ALLOWANCE = {
    "SILVER": 2,
    "GOLD": 4,
    "RESIDENT_GOLD": 6,
}

# Group deposit per-head tiers and flats (PRD §3.7).
TIER1_PER_HEAD_CENTS = 3000   # party_size <= 5
TIER2_PER_HEAD_CENTS = 2600   # 6 <= party_size <= 12
TIER3_PER_HEAD_CENTS = 2200   # party_size >= 13
EXCLUSIVE_LANE_FLAT_CENTS = 20000
MIN_SHARED_DEPOSIT_CENTS = 8000

# Add-on discounts (PRD §3.8).
ADDON_FOOD_PASS_DISCOUNT = 0.15
ADDON_RESIDENT_DRINK_DISCOUNT = 0.10

# Tube height minimum (PRD §3.5).
MIN_TUBE_HEIGHT_CM = 92
