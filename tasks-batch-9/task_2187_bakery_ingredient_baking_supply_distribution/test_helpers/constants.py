"""Domain thresholds and literal constants drawn from the PRD's calculations."""

API_PREFIX = "/bakery-distribution"

# PRD §2.4 — the logical clock reads exactly this instant before any operator sets it.
LOGICAL_CLOCK_EPOCH = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.4 step one — one cent per pound is the absolute floor.
    "MIN_UNIT_PRICE_CENTS_PER_LB": 1,
    # PRD §3.4 step two — quantity discount bands.
    "DISCOUNT_TIER_1_MIN_LB": 2000,
    "DISCOUNT_TIER_1_RATE": 0.015,
    "DISCOUNT_TIER_2_MIN_LB": 10000,
    "DISCOUNT_TIER_2_RATE": 0.030,
    # PRD §3.4 step three — fuel surcharge rates.
    "BASE_FUEL_PCT": 0.025,
    "SURGE_FUEL_PCT": 0.040,
    # PRD §3.4 step three — volume rebate tiers keyed on subtotal + fuel surcharge.
    "REBATE_TIER_1_MIN_CENTS": 500000,
    "REBATE_TIER_1_RATE": 0.010,
    "REBATE_TIER_2_MIN_CENTS": 1500000,
    "REBATE_TIER_2_RATE": 0.025,
    # PRD §3.1 — default smallest priced drop value.
    "DEFAULT_MIN_DROP_CENTS": 25000,
    # PRD §3.6 — trailer compartment ceiling for a pneumatic fill plan.
    "TRAILER_COMPARTMENT_LB": 48000,
    "DEFAULT_MIN_FILL_LB": 2000,
    # PRD §3.9 — two compartments of 24000 pounds each.
    "ROUTE_COMPARTMENT_LB": 24000,
    "ROUTE_COMPARTMENT_COUNT": 2,
    "DEFAULT_SERVICE_BUFFER_MINUTES": 30,
    # PRD §3.11 — bench-hour thresholds and rates.
    "BILLABLE_HOURS_THRESHOLD": 4.0,
    "INCLUDED_HOURS": 2.0,
    "TIER1_HOURS": 8.0,
    "TIER1_RATE_CENTS": 18500,
    "TIER2_RATE_CENTS": 14500,
    "RED_TIER_MULTIPLIER": 1.250,
    # PRD §3.2 / §3.8 — bounded negotiation and revision cycles.
    "MAX_NEGOTIATION_ROUND": 3,
    "MAX_REVISION_ROUND": 2,
    # PRD §2.3 — pagination window.
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

# PRD §3.7 — allergen severity weights on a nought-to-one-hundred scale.
ALLERGEN_WEIGHT = {
    "NONE": 0.00,
    "SOY": 0.20,
    "EGG": 0.35,
    "DAIRY": 0.40,
    "GLUTEN": 0.55,
    "TREE_NUT": 0.90,
    "PEANUT": 1.00,
}
GLUTEN_FREE_CONFLICT_PENALTY = 15.00
RISK_TIER_AMBER_MIN = 25.00
RISK_TIER_RED_MIN = 60.00
RISK_SCORE_CEILING = 100.00

# PRD §3.4 step three — the two declared holiday surge windows.
SURGE_WINDOWS = (
    ("2026-03-15T00:00:00Z", "2026-04-15T00:00:00Z"),
    ("2026-11-15T00:00:00Z", "2026-12-31T00:00:00Z"),
)

# Values reused across fixtures so that pinned money literals stay reproducible.
TEST_DEFAULTS = {
    "CLOCK": "2026-08-05T00:00:00Z",
    "SERVICE_DATE": "2026-09-15T00:00:00Z",
    "REQUESTED_DELIVERY_ON": "2026-09-15T00:00:00Z",
    "CREDIT_LIMIT_CENTS": 5000000,
    "MIN_DROP_CENTS": 25000,
    "TERM_START_ON": "2026-09-01T00:00:00Z",
    "TERM_END_ON": "2026-12-31T00:00:00Z",
    "WINDOW_START_AT": "2026-09-15T08:00:00Z",
    "WINDOW_END_AT": "2026-09-15T10:00:00Z",
    "VEHICLE_CAPACITY_LB": 24000,
}
