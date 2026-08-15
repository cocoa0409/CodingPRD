"""Domain thresholds — numeric constants named by the PRD.

Weather minima (PRD §3.6), billing tiers and penalty bands (PRD §3.8),
season hard caps (PRD §3.5), suspension threshold (PRD §3.6), booking and
scheduling lead times (PRD §3.5/§3.6), credit validity (PRD §3.6).
"""

THRESHOLDS = {
    # Go/no-go weather minima (PRD §3.6)
    "VFR_MIN_VISIBILITY_SM": 3.0,
    "VFR_MIN_CEILING_FT": 1000,
    "MAX_WIND_KTS": 25,
    "MARGINAL_VISIBILITY_SM": 5.0,
    "MARGINAL_CEILING_FT": 1500,
    "MARGINAL_WIND_KTS": 18,
    # Tiered volume discount (PRD §3.8)
    "TIER1_MAX_HOURS": 20,
    "TIER2_MAX_HOURS": 50,
    "TIER1_DISCOUNT_PCT": 0,
    "TIER2_DISCOUNT_PCT": 5,
    "TIER3_DISCOUNT_PCT": 10,
    # Cancellation penalty notice bands (PRD §3.8)
    "FULL_NOTICE_HOURS": 72,
    "PARTIAL_NOTICE_HOURS": 24,
    "PARTIAL_PENALTY_PCT": 25,
    "LATE_PENALTY_PCT": 50,
    # Season hard caps (PRD §3.5)
    "AIRCRAFT_SEASON_HARD_CAP_HOURS": 600,
    "PILOT_SEASON_HARD_CAP_HOURS": 500,
    # Pickup-failure suspension threshold (PRD §3.6)
    "SUSPENSION_THRESHOLD": 3,
    # Booking/scheduling lead times (PRD §3.5/§3.6)
    "MIN_BOOKING_LEAD_HOURS": 24,
    "MIN_SCHEDULE_LEAD_HOURS": 2,
    # Make-good credit validity (PRD §3.6)
    "MAKE_GOOD_VALIDITY_DAYS": 30,
    # Planned duration bounds (PRD §3.5)
    "MIN_PLANNED_DURATION_HOURS": 1,
    "MAX_PLANNED_DURATION_HOURS": 8,
}

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 30000,
    "MAX_TOW_WEIGHT_LBS": 500,
    "BANNER_LENGTH_FT": 50,
    "BANNER_WEIGHT_LBS": 100,
    "MIN_BANNER_LENGTH_FT": 10,
    "ROUTE_LENGTH_NM": 5,
    "QUOTA_HOURS": 100,
    "MONTH": "2026-08",
    "CLOCK_START": "2026-08-01T00:00:00Z",
}
