"""Domain thresholds — numeric constants named in the PRD (§2.7, §3)."""

THRESHOLDS = {
    # Pilot duty limits (PRD §3.4): eight hours flight time, fourteen hours duty span.
    "FLIGHT_LIMIT_MIN": 480,
    "DUTY_LIMIT_MIN": 840,
    "REPORT_OFFSET_MIN": 45,
    "DEBRIEF_OFFSET_MIN": 15,
    # Provisional estimate per-passenger allowance (PRD §3.5).
    "PAX_ALLOWANCE_LB": 5,
    # Minimum fuel ratio for the final manifest (PRD §3.7: sixty percent).
    "MIN_FUEL_RATIO_BPS": 6000,
    # Load-factor price tiers (PRD §3.5).
    "LOAD_TIER2_PCT": 50,
    "LOAD_TIER2_BPS": 11000,
    "LOAD_TIER3_PCT": 80,
    "LOAD_TIER3_BPS": 12500,
    "WEEKEND_BPS": 11000,
    "DEFAULT_BPS": 10000,
    # Cancellation settlement tiers (PRD §3.8): 24h full refund, 2h partial,
    # 75% credit leg, 10% partial fee, 365-day credit validity.
    "REFUND_FULL_MIN": 1440,
    "REFUND_PARTIAL_MIN": 120,
    "PARTIAL_FEE_BPS": 1000,
    "CREDIT_ONLY_BPS": 7500,
    "CREDIT_VALIDITY_DAYS": 365,
    # Complaint auto-match overflight pad (PRD §3.9: thirty minutes past arrival).
    "OVERFLIGHT_PAD_MIN": 30,
    # Tier-derived turnaround buffers (PRD §3.1).
    "TURN_SHORT_MIN": 15,
    "TURN_STANDARD_MIN": 25,
    "TURN_GRAND_MIN": 40,
}

# Default base configuration values (PRD §3.1).
BASE_DEFAULTS = {
    "weather_ceiling_min_ft": 1000,
    "weather_visibility_min_sm": 3,
    "weather_wind_max_kt": 25,
    "weather_validity_min": 60,
    "complaint_quota_threshold": 3,
    "complaint_window_days": 30,
    "hold_expire_minutes": 30,
}

# Startup logical clock instant (PRD §2.5).
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_SEAT_PRICE_CENTS": 25000,
    "ROUTE_DURATION_MIN": 25,
    "ROUTE_FUEL_LB": 300,
    "SEAT_CAPACITY": 4,
    "EMPTY_WEIGHT_LB": 1500,
    "EMPTY_MOMENT_LB_IN": 82500,
    "MAX_TAKEOFF_WEIGHT_LB": 2600,
    "FUEL_ARM_INCHES": 60,
    "CG_FORWARD_LIMIT_IN": 52,
    "CG_AFT_LIMIT_IN": 57,
    "WAIVER_VERSION": "WAV-1",
}
