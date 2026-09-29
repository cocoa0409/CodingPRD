"""Domain thresholds and canonical fixture inputs.

Every numeric constant here is stated verbatim in the PRD's calculation prose.
"""

# ─── Numeric thresholds named by the PRD ──────────────────────────────────────

THRESHOLDS = {
    # Sequencing and the haul chain.
    "AVERAGE_HAUL_SPEED_MPH": 45,
    "MAX_DRIVING_HOURS_PER_SHIFT": 11,
    "REST_BLOCK_HOURS": 10,
    "LOAD_OUT_BUFFER_HOURS": 6,
    # Lot capacity charge.
    "SPACING_MULTIPLIER_MAJOR": 1.35,
    "SPACING_MULTIPLIER_FLAT": 1.20,
    "SPACING_MULTIPLIER_KIDDIE": 1.10,
    "SURGE_PCT_MAJOR": 25,
    "SURGE_PCT_FLAT": 15,
    "SURGE_PCT_KIDDIE": 0,
    "USABLE_AREA_PCT": 80,
    "CIRCULATION_SQFT_PER_ATTENDEE": 0.5,
    "AMPERAGE_HEADROOM_PCT": 90,
    # Ride occupation.
    "TRANSPORT_BUFFER_HOURS": 4,
    # Permits.
    "TRANSPORT_AXLE_SURCHARGE_CENTS": 1500,
    # Inspections.
    "INSPECTION_SLOT_TIME_UTC": "14:00:00Z",
    "OUT_OF_SERVICE_DEFECT_THRESHOLD": 3,
    # Labor.
    "OVERTIME_THRESHOLD_HOURS": 10,
    "OVERTIME_MULTIPLIER": 1.5,
    "RIGGING_PREMIUM_PCT": 10,
    "HOUSING_STIPEND_CENTS": 3500,
    "VISA_EXPIRING_WINDOW_DAYS": 30,
    # Settlement.
    "OPERATING_HOURS_PER_DAY": 8,
    "TIER_1_NET_CENTS": 2_000_000,
    "TIER_1_BONUS_PP": 2.5,
    "TIER_2_NET_CENTS": 5_000_000,
    "TIER_2_BONUS_PP": 5.0,
    "EFFECTIVE_PCT_CAP": 72.5,
    "RIDE_SHORTFALL_PENALTY_CENTS": 25_000,
    "RIDE_SHORTFALL_CAP_PCT_OF_SPLIT": 10,
    # Weather and make-goods.
    "ABATEMENT_FLOOR_HOURS": 2,
    "MAKEGOOD_MULTIPLIER_CASH_REFUND": 1.00,
    "MAKEGOOD_MULTIPLIER_SPONSOR_CREDIT": 1.25,
    "MAKEGOOD_MULTIPLIER_BONUS_DAY": 0.00,
    "MAKEGOOD_CAP_PCT_OF_GUARANTEE": 30,
    # Negotiation.
    "NEGOTIATION_ROUND_BUDGET": 2,
    # Jurisdiction defaults.
    "DEFAULT_INSPECTION_SLOT_CAPACITY_PER_DAY": 2,
    "DEFAULT_MAX_CONSECUTIVE_WORK_DAYS": 6,
    # Pagination.
    "DEFAULT_LIMIT": 10,
    "MAX_LIMIT": 100,
}


# ─── The logical clock ────────────────────────────────────────────────────────

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_BEFORE_LOAD_IN = "2026-08-20T00:00:00Z"
CLOCK_AT_LOAD_IN = "2026-09-01T07:00:00Z"
CLOCK_AT_OPEN = "2026-09-04T12:00:00Z"
CLOCK_MID_RUN = "2026-09-05T18:00:00Z"
CLOCK_AT_CLOSE = "2026-09-07T12:00:00Z"


# ─── Canonical lot calendar used across the fixtures ──────────────────────────

STOP_LOAD_IN_START = "2026-09-01T06:00:00Z"
STOP_OPEN_DATE = "2026-09-04T12:00:00Z"
STOP_CLOSE_DATE = "2026-09-07T12:00:00Z"
STOP_TEARDOWN_DEADLINE = "2026-09-08T12:00:00Z"

TRANSPORT_PERMIT_VALID_FROM = "2026-09-01T00:00:00Z"
TRANSPORT_PERMIT_VALID_UNTIL = "2026-09-09T00:00:00Z"
EVENT_PERMIT_VALID_FROM = "2026-09-04T00:00:00Z"
EVENT_PERMIT_VALID_UNTIL = "2026-09-08T00:00:00Z"


# ─── Canonical reference-data inputs ──────────────────────────────────────────

TEST_DEFAULTS = {
    # Jurisdiction.
    "STATE_CODE": "OH",
    "STATE_NAME": "Ohio",
    "PERMIT_LEAD_DAYS": 10,
    "AMUSEMENT_TAX_PCT": 6.5,
    "PERMIT_FEE_CENTS": 50000,
    # Lot.
    "VENUE_NAME": "Franklin County Fairgrounds",
    "VENUE_CITY": "Columbus",
    "LOT_AREA_SQFT": 100000,
    "POWER_AMPS_AVAILABLE": 1200,
    "EXPECTED_ATTENDANCE": 20001,
    # Route.
    "ROUTE_NAME": "2026 Midwest Swing",
    "SEASON_YEAR": 2026,
    "HOME_BASE_STATE": "OH",
    # Deal.
    "COUNTERPARTY_NAME": "Franklin County Agricultural Society",
    "REVENUE_SPLIT_PCT_OPERATOR": 65,
    "GUARANTEE_CENTS": 900000,
    # Rides.
    "MAJOR_RIDE_NAME": "Giant Wheel",
    "MAJOR_FOOTPRINT_SQFT": 4010,
    "MAJOR_POWER_AMPS": 300,
    "FLAT_RIDE_NAME": "Tilt-A-Whirl",
    "FLAT_FOOTPRINT_SQFT": 2003,
    "FLAT_POWER_AMPS": 120,
    "KIDDIE_RIDE_NAME": "Kiddie Coaster",
    "KIDDIE_FOOTPRINT_SQFT": 905,
    "KIDDIE_POWER_AMPS": 60,
    # Workers.
    "WORKER_NAME": "Op One",
    "HOURLY_RATE_CENTS": 1600,
}
