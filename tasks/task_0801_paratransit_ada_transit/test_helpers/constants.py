"""Domain thresholds — numeric constants stated verbatim in the PRD.

Only constants the PRD pins to an explicit numeric value appear here. Point
values per no-show / late-cancel event, the trip duration, the late-cancel
lead time, and the certification-validity period are referenced in the PRD as
named quantities WITHOUT a numeric value, so they are deliberately absent —
no test asserts against them.
"""

# Fare arithmetic (PRD §3.8)
CROSS_ZONE_SURCHARGE_CENTS = 150
FARE_CAP_MULTIPLIER = 2
COMPANION_FARE_CENTS = 275

# No-show scoring windows and tiers (PRD §2.10)
ROLLING_WINDOW_DAYS = 30
WARNING_THRESHOLD_POINTS = 3
SUSPENSION_THRESHOLD_POINTS = 6
TIER1_SUSPENSION_DAYS = 7
TIER2_SUSPENSION_DAYS = 15
TIER3_SUSPENSION_DAYS = 30

# Service-area geometry (PRD §2.7)
R_MILES = 3958.7613
DEFAULT_SERVICE_RADIUS_MILES = 0.75

# Pickup window / turnaround buffer (PRD §3.8, §3.6)
PICKUP_WINDOW_MINUTES = 30
TURNAROUND_BUFFER_MINUTES = 15

# Convenience defaults used by factories/fixtures (not asserted as PRD rules).
TEST_DEFAULTS = {
    "ZA_CENTER_LAT": 40.0,
    "ZA_CENTER_LNG": -74.0,
    "ZB_CENTER_LAT": 40.05,
    "ZB_CENTER_LNG": -74.0,
    "ZA_BASE_FARE_CENTS": 500,
    "ZA_FIXED_ROUTE_FARE_CENTS": 290,
    "ZB_BASE_FARE_CENTS": 700,
    "ZB_FIXED_ROUTE_FARE_CENTS": 290,
    # Latitude on the 0.75-mi service boundary due north of ZA center (haversine,
    # R=3958.7613). The exact inverse-haversine latitude (40.010854868844724) rounds
    # to a great-circle distance of 0.7500000011 mi — a hair PAST 0.75 from float
    # round-trip error — so a faithful inclusive (<=) check would reject it. This value
    # sits on the inclusive side (distance 0.7499994 mi, ~1mm inside), exercising the
    # "point exactly on the boundary is in-service" rule without a false rejection.
    "BOUNDARY_LAT_075_MI_NORTH": 40.01085486,
    # A point ~69 mi north of ZA center — well outside the 0.75-mi radius.
    "OUT_OF_AREA_LAT": 41.0,
    "CLOCK_DEFAULT": "2026-06-01T00:00:00Z",
}
