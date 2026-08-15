"""Domain thresholds and test defaults — numeric constants stated in the PRD.

Only constants whose values the PRD states verbatim belong here. The PRD names
O2_TOLERANCE_PCT, ROOM_EMPTY_DAYS, PRIORITY_OPEN_DAYS, and PRIORITY_RELEASE_DAYS
without giving their values, so no test may assert an outcome that depends on
those values.
"""

# PRD-stated domain constants
PACKING_CHARGE_PER_CARTON_CENTS = 650      # "650 cents for every packed carton"
ESTIMATED_PRICE_FLOOR_CENTS = 1000         # "the floor of 1,000 cents per carton"
ADVANCE_RATE = 0.60                        # "times 0.60, rounded half-up"
DECAY_PRIORITY_THRESHOLD_PCT = 5.0         # "reaches at least 5.0 percent"

# Logical clock startup default (PRD: the clock reads exactly this instant
# when it has never been set).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# A newly registered room reads ambient air (PRD-stated value).
AMBIENT_O2_PCT = 20.9

# Shared test defaults (chosen by the tests, not by the PRD).
TEST_DEFAULTS = {
    "ORCHARD_NAME": "Riverview",
    "BLOCK_CODE": "B1",
    "VARIETY": "GALA",
    "STORAGE_LIFE_DAYS": 240,
    "ROOM_CODE": "R1",
    "BIN_CAPACITY": 40,
    "O2_SETPOINT_PCT": 1.5,
    "PLANNED_OPEN_DATE": "2026-11-01T00:00:00Z",
    "CUSTOMER_NAME": "RetailCo",
    "LABEL_CODE": "RC-TRAY",
    "GRADE_MIN": "EXTRA_FANCY",
    "COLOR_MIN_PCT": 66,
    "SIZE_CLASS": "MEDIUM",
    "PACK_STYLE": "TRAY",
    "GRADE_CLASS": "EXTRA_FANCY",
    "SEASON": "2026-2027",
    "LINE_CODE": "LINE_1",
    "RUN_START": "2026-08-02T08:00:00Z",
    "RUN_END": "2026-08-02T12:00:00Z",
}
