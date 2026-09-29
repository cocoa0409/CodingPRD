"""Domain constants for the touring motorsports series promotion API.

Every value here is taken directly from the PRD: the global thresholds that gate
booking, staging, inspection, marketing and settlement behaviour, the enum value
sets, and the canonical fixture defaults the composite helpers build on.
"""

from __future__ import annotations

from typing import Dict, Final, List

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: Value the logical clock reads before it has ever been set (PRD 2.4).
CLOCK_DEFAULT_UTC: Final[str] = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Booking, calendar and rotation
# ---------------------------------------------------------------------------

#: A tour date must be at least this many whole days after the logical clock.
BOOKING_LEAD_TIME_DAYS: Final[int] = 45

#: A booking may be countered/revised only while the round counter is below this.
MAX_NEGOTIATION_ROUNDS: Final[int] = 3

#: Default minimum whole days between two CONFIRMED bookings in one market.
DEFAULT_MARKET_ROTATION_COOLDOWN_DAYS: Final[int] = 21

#: Default hours of turnaround padding applied after a venue occupancy interval.
DEFAULT_VENUE_TURNAROUND_HOURS: Final[int] = 12

# ---------------------------------------------------------------------------
# Transport chain (one-sided haul buffer)
# ---------------------------------------------------------------------------

#: Average transporter speed used to convert haul miles into driving hours.
HAUL_AVG_MPH: Final[int] = 50

#: Mandatory rest added on top of the driving hours.
HAUL_REST_HOURS: Final[int] = 10

# ---------------------------------------------------------------------------
# Staging window and staging bays
# ---------------------------------------------------------------------------

#: The staging window opens this many hours before show_start_utc (inclusive).
STAGING_OPEN_HOURS_BEFORE_SHOW: Final[int] = 8

#: The staging window closes this many hours before show_start_utc (inclusive).
STAGING_CLOSE_HOURS_BEFORE_SHOW: Final[int] = 2

#: At or above this race weight an entry is a heavy rig and takes the highest
#: free staging bay index; a lighter rig takes the lowest free index.
HEAVY_VEHICLE_LBS: Final[int] = 9000

# ---------------------------------------------------------------------------
# Technical inspection
# ---------------------------------------------------------------------------

#: An inspection attempt is admissible only while tech_attempt_count is below this.
MAX_TECH_ATTEMPTS: Final[int] = 3

# ---------------------------------------------------------------------------
# Run order timeline
# ---------------------------------------------------------------------------

#: Floor reset inserted between two consecutive COMPETITION segments.
FLOOR_RESET_MINUTES: Final[int] = 8

# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------

#: Both scoring variants start from this base before penalties.
READINESS_BASE_SCORE: Final[int] = 100

#: Road miles per complete block that attracts the haul penalty.
READINESS_HAUL_BLOCK_MILES: Final[int] = 500

#: Points deducted per complete haul block.
READINESS_HAUL_PENALTY_PER_BLOCK: Final[int] = 5

#: Points deducted when the arrival is late (projected or actual).
READINESS_SCHEDULE_PENALTY: Final[int] = 15

#: Points deducted per accumulated failed inspection attempt.
READINESS_FAILED_ATTEMPT_PENALTY: Final[int] = 25

#: Extra points deducted when the most recent inspection is CONDITIONAL.
READINESS_CONDITIONAL_PENALTY: Final[int] = 10

#: Inclusive clamp bounds for the readiness score.
READINESS_SCORE_MIN: Final[int] = 0
READINESS_SCORE_MAX: Final[int] = 100

# ---------------------------------------------------------------------------
# Sponsorship
# ---------------------------------------------------------------------------

#: Committed branding slots on one vehicle entry may not exceed this.
MAX_BRANDING_SLOTS_PER_VEHICLE: Final[int] = 4

#: Fraction of an activation fee recognized while the activation is ACTIVATED.
SPONSOR_HOLDBACK_PCT: Final[float] = 0.50

# ---------------------------------------------------------------------------
# Ticketing
# ---------------------------------------------------------------------------

#: Discount applied to the pit-party add-on when it is bundled with tickets.
PIT_PARTY_BUNDLE_DISCOUNT_PCT: Final[float] = 0.15

# ---------------------------------------------------------------------------
# Marketing budget caps
# ---------------------------------------------------------------------------

#: One stop may draw at most this fraction of the season's marketing budget.
STOP_MARKETING_CAP_PCT: Final[float] = 0.20

#: Per-channel fraction of the season's marketing budget.
CHANNEL_CAP_PCT: Final[Dict[str, float]] = {
    "RADIO": 0.40,
    "DIGITAL": 0.60,
    "GRASSROOTS": 0.30,
}

# ---------------------------------------------------------------------------
# Safety provisioning requirement floors
# ---------------------------------------------------------------------------

#: Attendance at or above this adds a second ALS medic and a second access lane.
SAFETY_ATTENDANCE_STEP: Final[int] = 6000

#: Live entry count at or above this adds a third ALS medic.
SAFETY_ENTRY_COUNT_ALS_STEP: Final[int] = 12

#: Attendance is divided by this (rounded up) for the BLS floor.
SAFETY_BLS_ATTENDANCE_DIVISOR: Final[int] = 2500

#: Minimum BLS medics regardless of attendance.
SAFETY_BLS_MIN: Final[int] = 2

#: Live entry count is divided by this (rounded up) for the ambulance floor.
SAFETY_AMBULANCE_ENTRY_DIVISOR: Final[int] = 10

#: Minimum ambulances regardless of entry count.
SAFETY_AMBULANCE_MIN: Final[int] = 1

#: Required catch fence height with and without a heavy rig among live entries.
SAFETY_FENCE_HEIGHT_HEAVY_FT: Final[int] = 8
SAFETY_FENCE_HEIGHT_LIGHT_FT: Final[int] = 6

#: Minimum emergency access lanes regardless of attendance.
SAFETY_LANES_MIN: Final[int] = 1

#: Barrier floor is max(SAFETY_BARRIER_MIN_FT, BASE + PER_ENTRY * live entries).
SAFETY_BARRIER_MIN_FT: Final[int] = 1200
SAFETY_BARRIER_BASE_FT: Final[int] = 900
SAFETY_BARRIER_PER_ENTRY_FT: Final[int] = 75

# ---------------------------------------------------------------------------
# Safety provisioning cost rates (integer cents)
# ---------------------------------------------------------------------------

ALS_STAFF_COST_CENTS: Final[int] = 45000
BLS_STAFF_COST_CENTS: Final[int] = 28000
AMBULANCE_COST_CENTS: Final[int] = 120000
BARRIER_COST_PER_FOOT_CENTS: Final[int] = 350

# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

#: Purse paid per STAGED vehicle entry at settlement.
PURSE_PER_ENTRY_CENTS: Final[int] = 150000

#: Marketing co-op credit tiers, evaluated against rental_due_pre_credit_cents
#: in descending threshold order; the first match wins.
MARKETING_COOP_TIERS: Final[List[tuple]] = [
    (5000000, 0.06),
    (2500000, 0.04),
]

#: Co-op credit applied when no tier threshold is met.
MARKETING_COOP_DEFAULT_PCT: Final[float] = 0.02

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT: Final[int] = 10
MIN_PAGE_LIMIT: Final[int] = 1
MAX_PAGE_LIMIT: Final[int] = 100

# ---------------------------------------------------------------------------
# Enum value sets
# ---------------------------------------------------------------------------

SEASON_STATUSES: Final[List[str]] = ["PLANNING", "CLOSED"]
VENUE_FLOOR_TYPES: Final[List[str]] = ["DIRT", "CONCRETE", "ASPHALT"]
BOOKING_STATES: Final[List[str]] = [
    "TERMS_PROPOSED",
    "COUNTERED",
    "CONFIRMED",
    "WITHDRAWN",
]
TERMS_SOURCES: Final[List[str]] = ["PROMOTER", "VENUE"]
SALES_STATES: Final[List[str]] = [
    "SALES_PENDING",
    "ON_SALE",
    "SALES_HALTED",
    "SALES_CLOSED",
    "SETTLED",
    "CANCELLED",
]
SAFETY_STATES: Final[List[str]] = [
    "SAFETY_DRAFT",
    "SAFETY_REVIEW",
    "SAFETY_CERTIFIED",
    "SAFETY_SUSPENDED",
]
READINESS_POSTURES: Final[List[str]] = ["OPEN", "RESTRICTED", "FROZEN"]
VEHICLE_CLASSES: Final[List[str]] = ["LIGHT", "HEAVY"]
LOGISTICS_STATES: Final[List[str]] = ["ENTERED", "STAGED", "WITHDRAWN"]
TECH_STATUSES: Final[List[str]] = [
    "TECH_PENDING",
    "TECH_CLEARED",
    "TECH_CONDITIONAL",
    "TECH_HELD",
]
READINESS_VARIANTS: Final[List[str]] = ["PRE_STAGING", "POST_STAGING"]
INSPECTION_RESULTS: Final[List[str]] = ["PASSED", "CONDITIONAL", "FAILED"]
DEFECT_SEVERITIES: Final[List[str]] = ["NONE", "MINOR", "MAJOR", "CRITICAL"]
SEGMENT_TYPES: Final[List[str]] = ["COMPETITION", "INTERMISSION"]
ORDER_STATUSES: Final[List[str]] = ["PENDING", "PAID", "REFUNDED", "VOID"]
VOID_REASONS: Final[List[str]] = ["SALES_HALTED", "SALES_CLOSED", "STOP_CANCELLED"]
SPONSOR_CATEGORIES: Final[List[str]] = [
    "FUEL",
    "TIRE",
    "BEVERAGE",
    "RETAIL",
    "AUTOMOTIVE",
]
ACTIVATION_STATES: Final[List[str]] = ["PROPOSED", "ACTIVATED", "FULFILLED"]
SAFETY_PLAN_STATES: Final[List[str]] = ["DRAFT", "SUBMITTED", "CERTIFIED", "RETURNED"]
MARKETING_CHANNELS: Final[List[str]] = ["RADIO", "DIGITAL", "GRASSROOTS"]
MARKETING_STATES: Final[List[str]] = ["COMMITTED", "RELEASED"]
SETTLEMENT_STATES: Final[List[str]] = ["PREPARED", "DISPUTED", "APPROVED"]
SETTLEMENT_VARIANTS: Final[List[str]] = ["PROVISIONAL", "FINAL"]

#: return_reason written by the automatic plan return when requirements grow.
AUTO_REQUIREMENT_INCREASE: Final[str] = "AUTO_REQUIREMENT_INCREASE"

# ---------------------------------------------------------------------------
# Canonical fixture defaults
# ---------------------------------------------------------------------------

# Season
DEFAULT_SEASON_NAME: Final[str] = "2026-27 Thunder Tour"
DEFAULT_SEASON_YEAR: Final[int] = 2026
DEFAULT_SEASON_START_DATE: Final[str] = "2026-10-01"
DEFAULT_SEASON_END_DATE: Final[str] = "2027-03-31"
DEFAULT_SEASON_MARKETING_BUDGET_CENTS: Final[int] = 40000000

# Venue
DEFAULT_VENUE_NAME: Final[str] = "Atlanta Dome"
DEFAULT_VENUE_MARKET_CODE: Final[str] = "ATL"
DEFAULT_VENUE_CITY: Final[str] = "Atlanta"
DEFAULT_VENUE_STATE_CODE: Final[str] = "GA"
DEFAULT_VENUE_SEAT_CAPACITY: Final[int] = 9000
DEFAULT_VENUE_FLOOR_TYPE: Final[str] = "DIRT"
DEFAULT_VENUE_CATCH_FENCE_MAX_HEIGHT_FT: Final[int] = 10
DEFAULT_VENUE_MEDICAL_BAY_COUNT: Final[int] = 2
DEFAULT_VENUE_LOAD_IN_HOURS_REQUIRED: Final[int] = 10
DEFAULT_VENUE_STAGING_BAY_COUNT: Final[int] = 4

# Booking
DEFAULT_TOUR_DATE: Final[str] = "2026-11-14"
DEFAULT_RENTAL_BASE_CENTS: Final[int] = 3000000
DEFAULT_REVENUE_SHARE_PCT: Final[float] = 0.12
DEFAULT_PER_TICKET_FACILITY_FEE_CENTS: Final[int] = 350
DEFAULT_LOAD_IN_START_UTC: Final[str] = "2026-11-13T14:00:00Z"
DEFAULT_TEAR_DOWN_END_UTC: Final[str] = "2026-11-15T06:00:00Z"

# Show timing
DEFAULT_DOORS_OPEN_UTC: Final[str] = "2026-11-14T22:00:00Z"
DEFAULT_SHOW_START_UTC: Final[str] = "2026-11-14T23:00:00Z"
DEFAULT_SHOW_WINDOW_MINUTES: Final[int] = 150
DEFAULT_PIT_PARTY_PRICE_CENTS: Final[int] = 2450
DEFAULT_PIT_PARTY_CAPACITY: Final[int] = 400

# Ticket tiers
DEFAULT_TIER_CODE: Final[str] = "PITSIDE"
DEFAULT_TIER_PRICE_CENTS: Final[int] = 4750
DEFAULT_TIER_ALLOTMENT: Final[int] = 3000
DEFAULT_SECOND_TIER_CODE: Final[str] = "UPPER"
DEFAULT_SECOND_TIER_PRICE_CENTS: Final[int] = 2500
DEFAULT_SECOND_TIER_ALLOTMENT: Final[int] = 3000
DEFAULT_ON_SALE_START_UTC: Final[str] = "2026-08-01T00:00:00Z"
DEFAULT_ON_SALE_END_UTC: Final[str] = "2026-11-14T18:00:00Z"
DEFAULT_GROUP_MIN_QTY: Final[int] = 20
DEFAULT_GROUP_DISCOUNT_PCT: Final[float] = 0.125

# Safety plan
DEFAULT_BARRIER_LINEAR_FEET: Final[int] = 1600
DEFAULT_CATCH_FENCE_HEIGHT_FT: Final[int] = 8
DEFAULT_ALS_STAFF_COUNT: Final[int] = 2
DEFAULT_BLS_STAFF_COUNT: Final[int] = 3
DEFAULT_AMBULANCE_COUNT: Final[int] = 1
DEFAULT_EMERGENCY_ACCESS_LANES: Final[int] = 2

# Competitor and vehicle entry
DEFAULT_TEAM_NAME: Final[str] = "Thunder Ridge Racing"
DEFAULT_DRIVER_NAME: Final[str] = "R. Anderson"
DEFAULT_HOME_MARKET_CODE: Final[str] = "CLT"
DEFAULT_VEHICLE_CLASS: Final[str] = "LIGHT"
DEFAULT_VEHICLE_NUMBER: Final[str] = "11"
DEFAULT_VEHICLE_WEIGHT_LBS: Final[int] = 7200
DEFAULT_HAUL_DISTANCE_MILES: Final[int] = 1200
DEFAULT_SCHEDULED_ARRIVAL_UTC: Final[str] = "2026-11-14T16:00:00Z"

#: An instant inside the staging window of DEFAULT_SHOW_START_UTC.
DEFAULT_CHECK_IN_CLOCK_UTC: Final[str] = "2026-11-14T17:00:00Z"

# Sponsor and activation
DEFAULT_SPONSOR_COMPANY_NAME: Final[str] = "Redline Fuel"
DEFAULT_SPONSOR_CATEGORY: Final[str] = "FUEL"
DEFAULT_SPONSOR_CONTACT_EMAIL: Final[str] = "sponsor@redline.example"
DEFAULT_ACTIVATION_FEE_CENTS: Final[int] = 1500000
DEFAULT_VEHICLE_BRANDING_SLOTS: Final[int] = 2
DEFAULT_SIGNAGE_UNITS: Final[int] = 6
DEFAULT_HOSPITALITY_SEAT_COUNT: Final[int] = 20

# Marketing
DEFAULT_MARKETING_CHANNEL: Final[str] = "RADIO"
DEFAULT_MARKETING_AMOUNT_CENTS: Final[int] = 800000

# Ticket order
DEFAULT_PURCHASER_NAME: Final[str] = "A. Buyer"
DEFAULT_PURCHASER_EMAIL: Final[str] = "buyer@example.com"
DEFAULT_ORDER_QTY: Final[int] = 4

# Secondary markets used by multi-stop helpers
SECOND_VENUE_NAME: Final[str] = "Dallas Coliseum"
SECOND_VENUE_MARKET_CODE: Final[str] = "DAL"
SECOND_VENUE_CITY: Final[str] = "Dallas"
SECOND_VENUE_STATE_CODE: Final[str] = "TX"
SECOND_TOUR_DATE: Final[str] = "2026-12-05"
SECOND_LOAD_IN_START_UTC: Final[str] = "2026-12-04T14:00:00Z"
SECOND_TEAR_DOWN_END_UTC: Final[str] = "2026-12-06T06:00:00Z"
SECOND_DOORS_OPEN_UTC: Final[str] = "2026-12-05T22:00:00Z"
SECOND_SHOW_START_UTC: Final[str] = "2026-12-05T23:00:00Z"

THIRD_VENUE_NAME: Final[str] = "Omaha Pavilion"
THIRD_VENUE_MARKET_CODE: Final[str] = "OMA"
THIRD_VENUE_CITY: Final[str] = "Omaha"
THIRD_VENUE_STATE_CODE: Final[str] = "NE"
THIRD_TOUR_DATE: Final[str] = "2027-01-09"
THIRD_LOAD_IN_START_UTC: Final[str] = "2027-01-08T14:00:00Z"
THIRD_TEAR_DOWN_END_UTC: Final[str] = "2027-01-10T06:00:00Z"
THIRD_DOORS_OPEN_UTC: Final[str] = "2027-01-09T22:00:00Z"
THIRD_SHOW_START_UTC: Final[str] = "2027-01-09T23:00:00Z"
