"""Domain thresholds — numeric constants stated in PRD §3 prose."""

# Logical clock (PRD §2.5): before any set, the clock reads 2026-05-01T00:00:00Z.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
SETUP_CLOCK = "2026-06-01T00:00:00Z"

# Default event window used by fixtures: Saturday 2026-06-20 14:00-22:00 UTC.
DEFAULT_EVENT_START = "2026-06-20T14:00:00Z"
DEFAULT_EVENT_END = "2026-06-20T22:00:00Z"

THRESHOLDS = {
    # PRD §3.3 jurisdiction lead time in days.
    "LEAD_DAYS": {"CITY": 14, "COUNTY": 28, "STATE_ROUTE": 45},
    # PRD §3.2 petition threshold ratios (percent of households / businesses).
    "RESIDENTIAL_HOUSEHOLD_RATIO": 0.60,
    "MIXED_BUSINESS_WEIGHT": 0.50,
    "REQUIRED_SIGNATURES_MIN": 1,
    # PRD §3.4 traffic safety: emergency lane minimum width (metres).
    "EMERGENCY_LANE_MIN_WIDTH_M": 6.0,
    # PRD §3.4 barricade minimum: ceil(length_m / 12) + 4 when arterial.
    "BARRICADE_METRES_EACH": 12,
    "BARRICADE_ARTERIAL_BONUS": 4,
    # PRD §3.4 sound rules: 70 dB cap; 22:00 Fri/Sat else 21:00 cutoff.
    "SOUND_DB_CAP": 70,
    "SOUND_CUTOFF_WEEKEND": "22:00",
    "SOUND_CUTOFF_OTHER": "21:00",
    # PRD §3.4 insurance: $1M coverage floor; waiver attendance ceiling 75.
    "INSURANCE_COVERAGE_MIN_CENTS": 100000000,
    "WAIVER_MAX_ATTENDANCE": 75,
    # PRD §3.3/§3.5 permit fee schedule (integer cents).
    "FEE_BASE_CENTS": 5000,
    "FEE_TIER1_MAX_ATTENDANCE": 50,
    "FEE_TIER2_MAX_ATTENDANCE": 150,
    "FEE_TIER2_CENTS": 4000,
    "FEE_TIER3_CENTS": 9000,
    "FEE_ALCOHOL_CENTS": 7500,
    "FEE_SOUND_CENTS": 2500,
    "FEE_STATE_ROUTE_CENTS": 10000,
    # PRD §3.5 large-event discount and admin surcharge.
    "LARGE_EVENT_THRESHOLD_CENTS": 20000,
    "ADMIN_SURCHARGE_RATE": 0.03,
    # PRD §3.5/§3.6 equipment unit rates and per-line tax rate.
    "RATE_BARRICADE_CENTS": 250,
    "RATE_CONE_CENTS": 25,
    "RATE_SIGN_CENTS": 100,
    "EQUIPMENT_TAX_RATE": 0.0825,
    # PRD §3.7 deposit schedule (integer cents).
    "DEPOSIT_BASE_CENTS": 10000,
    "DEPOSIT_LARGE_CROWD_CENTS": 15000,
    "DEPOSIT_LARGE_CROWD_ATTENDANCE": 150,
    "DEPOSIT_ALCOHOL_CENTS": 20000,
    # PRD §3.7 contribution minimum; PRD §3.6 waiver cap.
    "CONTRIBUTION_MIN_CENTS": 100,
    "WAIVE_CAP_CENTS": 500,
    # PRD §3.6 late/shortage multipliers and grace hours.
    "LATE_MULTIPLIER": 2,
    "SHORTAGE_MULTIPLIER": 5,
    "DISPATCH_LEAD_HOURS": 48,
    "RETURN_GRACE_HOURS": 48,
    # PRD §3.8 report window hours after event_end_at.
    "REPORT_WINDOW_HOURS": 72,
}

TEST_DEFAULTS = {
    "SEGMENT_HOUSEHOLD_COUNT": 5,
    "SEGMENT_LENGTH_M": 12,
    "EXPECTED_ATTENDANCE": 40,
    "INSURANCE_COVERAGE_CENTS": 100000000,
    "INSURANCE_EXPIRES_ON": "2026-12-31",
}
