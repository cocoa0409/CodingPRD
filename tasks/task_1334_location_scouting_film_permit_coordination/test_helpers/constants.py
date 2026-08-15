"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Scout package photo floor (PRD §3.2)
    "PHOTO_FLOOR": 6,
    # Coverage score inclusive range (PRD §3.2)
    "COVERAGE_SCORE_MIN": 0,
    "COVERAGE_SCORE_MAX": 100,
    # Default negotiation round cap (PRD §3.2)
    "DEFAULT_MAX_ROUNDS": 5,
    # Large-cast trigger: cast_size strictly greater than this fires the multiplier (PRD §3.4)
    "LARGE_CAST_THRESHOLD": 50,
    # Basis-point denominator (PRD §2.8)
    "BPS_DENOMINATOR": 10_000,
    # Police monitor lane threshold: closed_lanes at or above forces POLICE staffing (PRD §3.8)
    "POLICE_MONITOR_LANE_THRESHOLD": 2,
    # Monitor base cadence: one monitor per 8 shoot hours, rounded up (PRD §3.8)
    "MONITOR_HOURS_BASE": 8,
    # Complaint response window: filed_at + 24h (PRD §3.9)
    "COMPLAINT_RESPONSE_HOURS": 24,
    # Deposit risk share: half of rate x window days (PRD §3.7)
    "DEPOSIT_RISK_NUMERATOR": 50,
    "DEPOSIT_RISK_DENOMINATOR": 100,
}

# Standard reference jurisdiction "LA-CITY" figures used across the READY chains.
REFERENCE_JURISDICTION = {
    "LEAD_TIME_BUSINESS_DAYS": 5,
    "NOTIFICATION_LEAD_CALENDAR_DAYS": 3,
    "NOTIFICATION_RADIUS_FT": 500,
    "BASE_FEE_CENTS": 100_000,
    "PER_DAY_FEE_CENTS": 50_000,
    "PER_LANE_FEE_CENTS": 20_000,
    "LARGE_CAST_THRESHOLD": 50,
    "LARGE_CAST_MULTIPLIER_BPS": 12_500,
    "MIN_LIABILITY_LIMIT_CENTS": 100_000_000,
    "POLICE_MONITOR_LANE_THRESHOLD": 2,
}

# Standard reference location figures.
REFERENCE_LOCATION = {
    "DEPOSIT_FLOOR_CENTS": 200_000,
    "BUFFER_DAYS": 2,
    "MAX_SHOOT_HOURS_PER_DAY": 14,
}

# Startup clock default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
