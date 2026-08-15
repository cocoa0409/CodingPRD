"""Domain thresholds and numeric constants from the PRD (§2.5, §3)."""

# Logical clock (PRD §2.5): startup default; never falls back to wall-clock time.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Crate geometry constants (PRD §3.2)
CLEARANCE_CM = {"STANDARD": 5, "DELICATE": 10, "HIGHLY_FRAGILE": 15}
THICKNESS_CM_TIERS = [(50, 1.2), (500, 1.8), (None, 2.5)]  # (weight ceiling, thickness)
BF_PER_M2 = 11
TARE_KG_PER_BF = 1.8
SHOCK_INDICATOR_G = {"STANDARD": 75, "DELICATE": 50, "HIGHLY_FRAGILE": 25}

# Item weight constants (PRD §3.1)
DIM_DIVISOR_CM3_PER_KG = 5000

# Quote constants (PRD §3.1)
QUOTE = {
    "WOOD_RATE_CENTS_PER_BF": 350,
    "WOOD_DISCOUNT_10_BF": 500,
    "WOOD_DISCOUNT_5_BF": 200,
    "HOURS_PER_M3": {"SHOP": 1.5, "ONSITE": 2.5},
    "RATE_CENTS_PER_HOUR": {"SHOP": 8500, "ONSITE": 12000},
    "TRAVEL_FLAT_CENTS_ONSITE": 15000,
    "INDICATOR_COST_CENTS": {75: 900, 50: 1200, 25: 1800},
    "BARRIER_COST_CENTS": {"NONE": 0, "VCI": 2500, "VACUUM_SEALED": 6000},
    "HAZMAT_SURCHARGE_CENTS": 4500,
    "HANDLING_TIERS": [(2000000, 0.03), (500000, 0.05)],  # (subtotal floor, rate); else 0.08
    "HANDLING_DEFAULT_RATE": 0.08,
    "FUEL_RATE": 0.09,
}

# Freight class tier floors, inclusive (PRD §3.4)
FREIGHT_CLASS_TIERS = [
    (800, "55"), (400, "60"), (200, "65"), (100, "70"),
    (50, "77.5"), (25, "85"), (10, "92.5"),
]
FREIGHT_CLASS_DEFAULT = "125"

# Container payloads (PRD §3.8)
CONTAINER_MAX_PAYLOAD_KG = {"20FT": 21770, "40FT": 26780, "40HC": 26680}

# Labor booking economics (PRD §3.6)
BOOKING_RATE_CENTS_PER_HOUR = {"SHOP": 8500, "ONSITE": 12000}
BOOKING_TRAVEL_SURCHARGE_CENTS = {"SHOP": 0, "ONSITE": 15000}

# Claims (PRD §3.9)
CLAIM_WINDOW_DAYS = 30
MOISTURE_WEEKLY_DEPRECIATION = 0.01
MOISTURE_FLOOR = 0.5
OTHER_CAP_FACTOR = 0.5

# Seal/reopen side effects (PRD §3.4)
REOPEN_SCRAP_BOARD_FEET = 2

# Common fixture item specs with PRD-derived expected values.
# 50x50x50 / 50 kg / STANDARD -> clearance 5, thickness 1.8, external 63.6,
# board_feet 27, tare 48.6, gross 98.6, volume 0.257259 m3.
STD50 = {
    "length_cm": 50, "width_cm": 50, "height_cm": 50, "weight_kg": 50,
    "fragile_class": "STANDARD", "board_feet": 27, "tare_kg": 48.6,
    "gross_kg": 98.6, "volume_m3": 0.257259, "indicator_g": 75, "barrier": "NONE",
}

# 100x80x60 / 40 kg / STANDARD -> board_feet 56, tare 100.8, gross 140.8;
# chargeable weight 96.0 (dimensional beats actual); SHOP provisional quote 34139.
STD100 = {
    "length_cm": 100, "width_cm": 80, "height_cm": 60, "weight_kg": 40,
    "fragile_class": "STANDARD", "board_feet": 56, "tare_kg": 100.8,
    "gross_kg": 140.8, "chargeable_kg": 96.0, "indicator_g": 75, "barrier": "NONE",
    "quote_shop": {"subtotal": 29000, "handling": 2320, "fuel": 2819, "total": 34139,
                   "hours": 1},
    "quote_onsite": {"subtotal": 59500, "handling": 4760, "fuel": 5783, "total": 70043,
                     "hours": 2, "labor": 39000},
}
