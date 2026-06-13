"""Domain thresholds — numeric constants from the PRD's calculations and gates."""

# Replacement-cost estimate (PRD §3.1)
CONSTRUCTION_RATE = {"FRAME": 120, "MASONRY": 150, "FIRE_RESISTIVE": 185}  # $/sqft
ROOF_RATE = {"FRAME": 18, "MASONRY": 22, "FIRE_RESISTIVE": 26}            # $/sqft
BLEND_UPLIFT = {"FRAME": 1.18, "MASONRY": 1.16, "FIRE_RESISTIVE": 1.15}
STORY_STEP = 0.04
ROOF_AGE_CAP = 20

# Wildfire score (PRD §3.2)
W_FUEL = 0.7
W_SLOPE = 0.5
W_SPACE = 0.3
SPACE_CAP = 200
MITIGATION_CREDIT = 12

# Wildfire insurability boundary (PRD §3.6)
WILDFIRE_UNINSURABLE_THRESHOLD = 80

# Annual premium (PRD §3.4)
TIER_RATE = [
    {"lo": 0, "hi": 200000, "rate": 0.0040},
    {"lo": 200000, "hi": 400000, "rate": 0.0035},
    {"lo": 400000, "hi": 999999999, "rate": 0.0031},
]
FLOOD_MULT = {"X": 1.0, "A": 1.2, "AE": 1.35, "VE": 1.6}
WIND_HAIL_MULT = {"TIER_1": 1.0, "TIER_2": 1.18, "TIER_3": 1.4}
DED_CREDIT = {1: 0.0, 2: 0.05, 5: 0.12}
WILDFIRE_SURCHARGE_FLOOR = 40
WILDFIRE_SURCHARGE_STEP = 0.005

# Wind/hail deductible (PRD §3.4)
MIN_DEDUCTIBLE = 2500

# Endorsement premium delta (PRD §3.5)
PERIL_RATE = {
    "WATER_BACKUP": 0.004,
    "SCREENED_ENCLOSURE": 0.003,
    "ORDINANCE_LAW": 0.0025,
    "EARTH_MOVEMENT": 0.006,
    "MOLD": 0.005,
}
EXCLUSION_CREDIT = {
    "WATER_BACKUP": 60,
    "SCREENED_ENCLOSURE": 45,
    "ORDINANCE_LAW": 80,
    "EARTH_MOVEMENT": 140,
    "MOLD": 70,
}

# Policy servicing (PRD §3.7)
REINSTATEMENT_FEE = 250
REINSTATEMENT_LAPSE_LIMIT = 2

# Wind/hail tier thresholds (PRD §3.2) — by distance_to_coast_mi
WIND_HAIL_TIER_3_MAX = 5    # < 5 -> TIER_3
WIND_HAIL_TIER_2_MAX = 50   # 5..50 -> TIER_2; > 50 -> TIER_1

# Inspection (PRD §3.3)
DEFAULT_BUFFER_MINUTES = 60
FOUR_POINT_PASS_COUNT = 4

# Property input ranges (PRD §3.1)
YEAR_BUILT_MIN = 1800
YEAR_BUILT_MAX = 2026
DEFAULT_STORIES = 1

# Allowed wind/hail deductible percents (PRD §3.4)
ALLOWED_DEDUCTIBLE_PCT = {1, 2, 5}
