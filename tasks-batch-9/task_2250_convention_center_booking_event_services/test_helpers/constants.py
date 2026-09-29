"""Numeric and calendar constants declared by the PRD.

Every value here is stated literally in the PRD prose; nothing is inferred.
"""

# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------

API_PREFIX = "/convention-center"

# --------------------------------------------------------------------------
# Clock (PRD §2.5)
# --------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Rental and deposit (PRD §3.1)
# --------------------------------------------------------------------------

MOVE_PERIOD_FACTOR = 0.5
DEPOSIT_PCT = 0.25

# --------------------------------------------------------------------------
# Actual-usage day weights (PRD §3.8)
# --------------------------------------------------------------------------

USAGE_FACTOR_MOVE_IN = 0.5
USAGE_FACTOR_SHOW = 1.0
USAGE_FACTOR_DARK = 0.125
USAGE_FACTOR_MOVE_OUT = 0.5
USAGE_FACTOR_HOLDOVER = 1.5

USAGE_FACTORS = {
    "MOVE_IN": USAGE_FACTOR_MOVE_IN,
    "SHOW": USAGE_FACTOR_SHOW,
    "DARK": USAGE_FACTOR_DARK,
    "MOVE_OUT": USAGE_FACTOR_MOVE_OUT,
    "HOLDOVER": USAGE_FACTOR_HOLDOVER,
}

# --------------------------------------------------------------------------
# Facility service fee bands (PRD §3.8)
# --------------------------------------------------------------------------

FEE_TIER_1_CENTS = 5_000_000
FEE_TIER_2_CENTS = 20_000_000
FEE_PCT_LOW = 0.09
FEE_PCT_MID = 0.07
FEE_PCT_HIGH = 0.055

# --------------------------------------------------------------------------
# Service order pricing (PRD §3.5)
# --------------------------------------------------------------------------

UTIL_TIER1_CENTS = 1200
UTIL_TIER2_CENTS = 900
UTIL_TIER3_CENTS = 700
UTIL_TIER1_UNITS = 100
UTIL_TIER2_UNITS = 400
RIG_POINT_CENTS = 25_000
CLEAN_SQFT_CENTS = 6
GUARD_HOUR_CENTS = 4_200
LATE_ORDER_FACTOR = 1.35
VENDOR_EXCLUSIVE_MULT = 1.00
VENDOR_PREFERRED_MULT = 1.10
VENDOR_OPEN_MULT = 1.25
SURCHARGE_CAP = 1.40
MIN_ORDER_CENTS = 15_000
ADVANCE_CUTOFF_DAYS = 30

# --------------------------------------------------------------------------
# Catering buyout (PRD §3.7)
# --------------------------------------------------------------------------

BUYOUT_PCT = 0.22
MIN_BUYOUT_CENTS = 250_000

# --------------------------------------------------------------------------
# Client standing (PRD §3.9)
# --------------------------------------------------------------------------

STANDING_THRESHOLD_CENTS = 10_000_000

# --------------------------------------------------------------------------
# Settlement dispute window (PRD §3.9)
# --------------------------------------------------------------------------

DISPUTE_WINDOW_HOURS = 240

# --------------------------------------------------------------------------
# Round caps (PRD §3.4, §3.9)
# --------------------------------------------------------------------------

MAX_AMENDMENT_ROUNDS = 3
MAX_SETTLEMENT_REVISION_ROUNDS = 2

# --------------------------------------------------------------------------
# Labor defaults (PRD §3.6)
# --------------------------------------------------------------------------

DEFAULT_MIN_CALL_HOURS = 4
DEFAULT_OVERTIME_MULTIPLIER = 1.5
DEFAULT_ST_WINDOW_START_HOUR = 8
DEFAULT_ST_WINDOW_END_HOUR = 17

# --------------------------------------------------------------------------
# Blackout defaults (PRD §3.10)
# --------------------------------------------------------------------------

DEFAULT_BUFFER_DAYS = 2

# --------------------------------------------------------------------------
# Hold release deadline (PRD §3.2)
# --------------------------------------------------------------------------

RELEASE_DEADLINE_MONTHS_BEFORE_SHOW = 3

# --------------------------------------------------------------------------
# Canonical policy window shapes used across the suite
# --------------------------------------------------------------------------

CITYWIDE_WINDOW = {
    "event_class": "CITYWIDE_CONVENTION",
    "priority_rank": 1,
    "open_months_before": 60,
    "close_months_before": 18,
    "max_holds_per_booking": 3,
    "challenge_response_hours": 120,
    "rental_discount_pct": 0.25,
    "max_challenge_rounds": 2,
}

LOCAL_EVENT_WINDOW = {
    "event_class": "LOCAL_EVENT",
    "priority_rank": 2,
    "open_months_before": 24,
    "close_months_before": 3,
    "max_holds_per_booking": 2,
    "challenge_response_hours": 72,
    "rental_discount_pct": 0.10,
    "max_challenge_rounds": 2,
}

CONSUMER_SHOW_WINDOW = {
    "event_class": "CONSUMER_SHOW",
    "priority_rank": 3,
    "open_months_before": 18,
    "close_months_before": 2,
    "max_holds_per_booking": 2,
    "challenge_response_hours": 48,
    "rental_discount_pct": 0.0,
    "max_challenge_rounds": 1,
}

# --------------------------------------------------------------------------
# Canonical space shapes
# --------------------------------------------------------------------------

MEETING_ROOM_301 = {
    "name": "Meeting Room 301",
    "space_class": "MEETING_ROOM",
    "rentable_sqft": 2600,
    "daily_base_rate_cents": 90_900,
}

BALLROOM_B = {
    "name": "Ballroom B",
    "space_class": "BALLROOM",
    "rentable_sqft": 40_000,
    "daily_base_rate_cents": 1_200_000,
}

BALLROOM_C = {
    "name": "Ballroom C",
    "space_class": "BALLROOM",
    "rentable_sqft": 42_000,
    "daily_base_rate_cents": 1_250_000,
}

HALL_A = {
    "name": "Hall A",
    "space_class": "HALL",
    "rentable_sqft": 200_000,
    "daily_base_rate_cents": 4_800_000,
    "rigging_capable": True,
}

HALL_A1 = {
    "name": "Hall A1",
    "space_class": "HALL",
    "rentable_sqft": 100_000,
    "daily_base_rate_cents": 2_400_000,
}

EXHIBIT_HALL_C = {
    "name": "Exhibit Hall C",
    "space_class": "HALL",
    "rentable_sqft": 100_000,
    "daily_base_rate_cents": 2_400_000,
    "rigging_capable": True,
}

# --------------------------------------------------------------------------
# Canonical client shapes
# --------------------------------------------------------------------------

SUNBELT_PROMOTER = {
    "legal_name": "Sunbelt Show Promotions",
    "contact_email": "ssp@example.org",
    "organization_type": "PROMOTER",
}

NATIONAL_WIDGET_ASSOCIATION = {
    "legal_name": "National Widget Association",
    "contact_email": "nwa@example.org",
    "organization_type": "NATIONAL_ASSOCIATION",
}

RIVERBEND_ROTARY = {
    "legal_name": "Riverbend Rotary",
    "contact_email": "rotary@example.org",
    "organization_type": "LOCAL_ORGANIZATION",
}

# --------------------------------------------------------------------------
# Canonical vendor shapes
# --------------------------------------------------------------------------

SPARKLECLEAN_EXCLUSIVE = {
    "legal_name": "SparkleClean Facility Services",
    "service_category": "CLEANING",
    "vendor_tier": "EXCLUSIVE",
    "coi_expiry_date": "2030-01-01",
}

VOLT_OPEN_UTILITIES = {
    "legal_name": "Volt Open Utilities",
    "service_category": "UTILITIES",
    "vendor_tier": "OPEN",
    "coi_expiry_date": "2030-01-01",
}

LAPSED_GUARD_CO = {
    "legal_name": "Lapsed Guard Co",
    "service_category": "SECURITY",
    "vendor_tier": "OPEN",
    "coi_expiry_date": "2026-07-01",
}

# --------------------------------------------------------------------------
# Canonical union jurisdiction shapes
# --------------------------------------------------------------------------

SEIU_LOCAL_3 = {
    "craft_name": "SEIU Local 3",
    "covered_category": "CLEANING",
    "straight_time_rate_cents": 9_533,
    "max_crew_hours_per_day": 40,
}

TEAMSTERS_LOCAL_7 = {
    "craft_name": "Teamsters Local 7",
    "covered_category": "UTILITIES",
    "straight_time_rate_cents": 8_000,
    "max_crew_hours_per_day": 12,
}
