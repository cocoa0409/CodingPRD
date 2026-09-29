"""Domain constants — every number here is stated verbatim in the PRD."""

# ─── Logical clock (PRD §2.4) ──────────────────────────────────────────────
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ─── Engineering gates (PRD §3.1) ──────────────────────────────────────────
MIN_REQUIRED_CYCLES = {
    "LIGHT_COMMERCIAL": 250_000,
    "FULL_COMMERCIAL": 500_000,
    "INSTITUTIONAL": 900_000,
}
REWORK_LIMIT = 3
SUPERSEDE_CHAIN_MAX_DEPTH = 5

# ─── Firmware support commitment (PRD §3.4) ────────────────────────────────
FIRMWARE_SUPPORT_DAYS = 1_825

# ─── Pricing (PRD §3.5 / §3.6) ─────────────────────────────────────────────
FINISH_SURCHARGE_CENTS = {
    "GRAPHITE": 0,
    "ARCTIC_WHITE": 4_500,
    "CLUB_RED": 7_500,
    "CUSTOM_BRAND_DECAL": 12_000,
    "PREMIUM_UPHOLSTERY": 26_000,
}
DUTY_UPLIFT = {
    "LIGHT_COMMERCIAL": 0.0,
    "FULL_COMMERCIAL": 0.06,
    "INSTITUTIONAL": 0.11,
}
INSTALL_LABOUR_RATE_CENTS_PER_HOUR = 8_875
VOLUME_DISCOUNT_TIERS = [
    (0, 5_000_000, 0.0),
    (5_000_000, 15_000_000, 0.04),
    (15_000_000, 40_000_000, 0.075),
    (40_000_000, None, 0.11),
]
FREIGHT_WAIVER_THRESHOLD_CENTS = 20_000_000
FREIGHT_RATE_CENTS_PER_KG = {"Z1": 180, "Z2": 260, "Z3": 340, "Z4": 520}
PUNCH_LIST_CREDIT_CENTS_PER_ITEM = 25_000
PROVISIONAL_INSTALL_HOURS_PER_UNIT = {
    "CARDIO": 1.5,
    "STRENGTH": 2.5,
    "CONNECTED": 3.0,
}

# ─── Warranty and installation (PRD §3.7) ──────────────────────────────────
WARRANTY_DAYS = {
    "LIGHT_COMMERCIAL": 365,
    "FULL_COMMERCIAL": 1_095,
    "INSTITUTIONAL": 1_825,
}
INSTALL_TRAVEL_BUFFER_MINUTES = 120

# ─── Preventive maintenance (PRD §3.8) ─────────────────────────────────────
PM_BASE_HOURS_PER_VISIT = {"CARDIO": 1.0, "STRENGTH": 0.6, "CONNECTED": 1.4}
PM_TIER_MULTIPLIER = {"BASIC": 1.0, "PRO": 1.25, "PLATINUM": 1.6}
USAGE_NORM_HOURS_PER_YEAR = 2_000
USAGE_FACTOR_MIN = 1.0
USAGE_FACTOR_MAX = 2.0

# ─── Trade-in valuation (PRD §3.9) ─────────────────────────────────────────
RESIDUAL_START = 0.55
RESIDUAL_PER_YEAR = 0.08
RESIDUAL_PER_VISIT = 0.015
RESIDUAL_FLOOR = 0.10
CONDITION_MULTIPLIER = {"A": 1.0, "B": 0.85, "C": 0.65}
UNSUPPORTED_CONSOLE_MULTIPLIER = 0.75

# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ─── Catalogue presets used by the test fixtures ───────────────────────────
# Each preset is a complete, PRD-legal equipment-model registration payload.
MODEL_PRESETS = {
    "T900": {
        "name": "T900 Treadmill",
        "category": "CARDIO",
        "duty_class": "FULL_COMMERCIAL",
        "unit_list_price_cents": 479_950,
        "shipping_weight_kg": 212.5,
        "allowed_finish_codes": ["GRAPHITE", "ARCTIC_WHITE", "CLUB_RED"],
    },
    "T950": {
        "name": "T950 Treadmill",
        "category": "CARDIO",
        "duty_class": "FULL_COMMERCIAL",
        "unit_list_price_cents": 519_950,
        "shipping_weight_kg": 218.0,
        "allowed_finish_codes": ["GRAPHITE"],
    },
    "S500": {
        "name": "S500 Selectorised Press",
        "category": "STRENGTH",
        "duty_class": "INSTITUTIONAL",
        "unit_list_price_cents": 324_575,
        "shipping_weight_kg": 341.0,
        "allowed_finish_codes": ["GRAPHITE", "CLUB_RED", "PREMIUM_UPHOLSTERY"],
    },
    "L200": {
        "name": "L200 Connected Cross-Trainer",
        "category": "CONNECTED",
        "duty_class": "LIGHT_COMMERCIAL",
        "unit_list_price_cents": 348_375,
        "shipping_weight_kg": 88.0,
        "allowed_finish_codes": ["GRAPHITE"],
        "console_platform": "CONSOLE_X",
    },
    "C700": {
        "name": "C700 Connected Bike",
        "category": "CONNECTED",
        "duty_class": "FULL_COMMERCIAL",
        "unit_list_price_cents": 561_325,
        "shipping_weight_kg": 96.5,
        "allowed_finish_codes": ["GRAPHITE", "CUSTOM_BRAND_DECAL"],
        "console_platform": "CONSOLE_T2",
    },
    "C750": {
        "name": "C750 Connected Bike",
        "category": "CONNECTED",
        "duty_class": "FULL_COMMERCIAL",
        "unit_list_price_cents": 599_000,
        "shipping_weight_kg": 99.0,
        "allowed_finish_codes": ["GRAPHITE"],
        "console_platform": "CONSOLE_T2",
    },
    "K900": {
        "name": "K900 Institutional Console Rower",
        "category": "CONNECTED",
        "duty_class": "INSTITUTIONAL",
        "unit_list_price_cents": 612_500,
        "shipping_weight_kg": 120.0,
        "allowed_finish_codes": ["GRAPHITE"],
        "console_platform": "CONSOLE_T1",
    },
}

# Default engineering target for each preset's first revision.
PRESET_TARGET_CYCLE_COUNT = {
    "T900": 500_000,
    "T950": 500_000,
    "S500": 950_000,
    "L200": 250_000,
    "C700": 500_000,
    "C750": 500_000,
    "K900": 950_000,
}

TEST_DEFAULTS = {
    "FACILITY_ACCOUNT_NAME": "Grandstand Fitness",
    "FACILITY_FREIGHT_ZONE": "Z1",
    "FACILITY_CREDIT_LIMIT_CENTS": 500_000_000,
    "PARTNER_NAME": "Meridian Service Co",
    "PARTNER_REGION": "R_NORTH",
    "PARTNER_TECHNICIAN_COUNT": 3,
    "PARTNER_HOURS_CAPACITY": 100.0,
    "PARTNER_TRAINING_UNTIL": "2027-12-31T00:00:00Z",
    "RIG_NAME": "RIG-A",
    "RIG_STATIONS": 2,
    "ORDER_WINDOW_START": "2026-09-10T08:00:00Z",
    "ORDER_WINDOW_END": "2026-09-10T18:00:00Z",
    "INSTALL_WINDOW_START": "2026-09-10T08:00:00Z",
    "INSTALL_WINDOW_END": "2026-09-10T11:00:00Z",
    "INSTALL_ESTIMATED_HOURS": 3.0,
    "RUN_ONE_WINDOW": ("2026-08-02T00:00:00Z", "2026-08-06T12:00:00Z"),
    "RUN_TWO_WINDOW": ("2026-08-06T00:00:00Z", "2026-08-10T12:00:00Z"),
    "LAYOUT_ZONE_LABEL": "Cardio Zone A",
}
