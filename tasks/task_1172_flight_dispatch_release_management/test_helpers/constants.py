"""Domain thresholds and standard test data values (PRD §3 calculations)."""

THRESHOLDS = {
    # Fuel computation (PRD §3.3)
    "WEIGHT_STEP_KG": 10000,
    "WEIGHT_STEP_PCT": 0.01,
    "WORST_HEADWIND_KTS": 50,
    "MIN_CONTINGENCY_KG": 100,
    "CONTINGENCY_PCT": 0.05,
    "FINAL_RESERVE_H": 0.5,
    "MAX_ALTERNATE_DISTANCE_NM": 200,
    # Manifest rollup (PRD §3.4)
    "PAX_KG": 87.5,
    "BAG_KG": 12.5,
    # Center of gravity (PRD §3.4)
    "ARM_OEW": 18.0,
    "ARM_PAX": 17.6,
    "ARM_BAG": 18.4,
    "ARM_CARGO": 19.5,
    "ARM_FUEL": 18.1,
    "CG_MIN_NORMAL": 20.0,
    "CG_MAX_NORMAL": 31.0,
    "CG_MIN_CDL": 22.0,
    "CG_MAX_CDL": 30.0,
    # En-route monitoring (PRD §3.8)
    "DIVERT_MARGIN_KG": 500,
    # MEL minima bump (PRD §3.6)
    "ALT_MINIMA_BUMP_CEILING_FT": 200,
    "ALT_MINIMA_BUMP_VIS_M": 500,
    # Delay auto-amendment (PRD §3.8)
    "DELAY_REVIEW_THRESHOLD_MIN": 60,
    # Desk-shift rest buffer (PRD §3.1)
    "REST_BUFFER_MIN": 30,
    # Dispatcher default capacity (PRD §3.1)
    "DEFAULT_MAX_ACTIVE_LEGS": 6,
}

# Standard reference data used by most scenario fixtures. The standard
# aircraft: tas 450, burn 2600, oew 42000 — with no manifest on the leg the
# weight reference is 42000 kg -> 5 weight steps -> effective burn 2730 kg/h.
TEST_DEFAULTS = {
    "CLOCK_START": "2026-05-01T00:00:00Z",
    "CLOCK_MORNING": "2026-05-01T08:00:00Z",
    "CLOCK_DEPART": "2026-05-01T10:30:00Z",
    "SHIFT_START": "2026-05-01T06:00:00Z",
    "SHIFT_END": "2026-05-01T14:00:00Z",
    "WX_FROM": "2026-05-01T09:00:00Z",
    "WX_TO": "2026-05-01T13:00:00Z",
    "WX_CEILING_FT": 1000,
    "WX_VISIBILITY_M": 5000,
    "STATION_MIN_CEILING_FT": 200,
    "STATION_MIN_VISIBILITY_M": 800,
    "RUNWAY_M": 2500,
    "ALT_DISTANCE_NM": 90,
    "LEG_DISTANCE_NM": 1200,
    "LEG_DEP": "2026-05-01T10:00:00Z",
    "LEG_ARR": "2026-05-01T12:30:00Z",
    "EVENT_ETA": "2026-05-01T11:30:00Z",
    "CRUISE_ALTITUDE_FT": 35000,
    "FORECAST_WIND_KTS": 30,
    "ROUTE_CODE": "DCT KLOSE DCT",
}

# Standard aircraft (A320): with no manifest, weight reference 42000 kg
# -> ceil(42000/10000) = 5 steps -> burn_eff 2600 * 1.05 = 2730 kg/h (PRD §3.3).
AIRCRAFT_A320 = {
    "tail_no": "N100AA",
    "type_code": "A320",
    "oew_kg": 42000,
    "mzfw_kg": 61000,
    "mtow_kg": 73500,
    "mlw_kg": 64500,
    "fuel_capacity_kg": 19000,
    "cruise_tas_kts": 450,
    "burn_kg_per_hour": 2600,
    "min_runway_m": 1800,
    "lemac_m": 17.0,
    "mac_m": 4.0,
}

# Pinned fuel figures of the standard 1200 NM FORECAST +30 kt plan on the
# standard aircraft (no manifest at compute time), derived per PRD §3.3:
# ground speed 480; exact trip 2.5 h * 2730 = 6825; contingency max(341.25, 100);
# alternate 90/450*2730 = 546; reserve 2730*0.5 = 1365; required 9077.25 -> 9077.
STANDARD_PLAN = {
    "ground_speed_kts": 480,
    "trip_fuel_kg": 6825,
    "mel_fuel_penalty_kg": 0,
    "contingency_kg": 341,
    "alternate_fuel_kg": 546,
    "final_reserve_kg": 1365,
    "required_fuel_kg": 9077,
    "burn_eff_kg_per_hour": 2730,
}
