"""Every pinned constant the PRD states, plus the logical-clock instants the
suite's canonical service day is replayed against.

Nothing here is invented: each value is quoted from the PRD section named in the
comment beside it.
"""

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# The deterministic logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

# "Before that clock is ever set, its value is `2026-08-01T00:00:00Z`."
UNSET_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The canonical service day. Reference data is registered well before the
# flight's cutoff, the counts lock at 03:00, the plan is cut at 04:00 and the
# aircraft departs at 10:00.
CLOCK_SETUP = "2026-09-12T09:00:00Z"
CLOCK_ORDERS = "2026-09-14T12:00:00Z"
CLOCK_LOCK = "2026-09-15T03:00:00Z"
CLOCK_PLAN = "2026-09-15T04:00:00Z"
CLOCK_PRODUCTION = "2026-09-15T04:30:00Z"
CLOCK_QA = "2026-09-15T05:00:00Z"
CLOCK_COMPLETE = "2026-09-15T05:30:00Z"
CLOCK_CART = "2026-09-15T06:10:00Z"
CLOCK_MANIFEST = "2026-09-15T07:00:00Z"
CLOCK_DISPATCH = "2026-09-15T07:25:00Z"
CLOCK_ARRIVE = "2026-09-15T07:50:00Z"
CLOCK_DELIVER = "2026-09-15T07:55:00Z"
CLOCK_UPLIFT = "2026-09-15T13:00:00Z"

# ---------------------------------------------------------------------------
# Airline contract defaults (PRD §3.1)
# ---------------------------------------------------------------------------

DEFAULT_SPECIAL_MEAL_CUTOFF_MINUTES = 720  # "defaulting to twelve hours"
MAX_SPECIAL_MEAL_CUTOFF_MINUTES = 4320  # "up to three days"
DEFAULT_LATE_DELIVERY_GRACE_MINUTES = 10  # "defaulting to ten minutes"
MAX_LATE_DELIVERY_GRACE_MINUTES = 120  # "up to two hours"
DEFAULT_UNUSED_RECOVERY_RATE_PCT = 30.00
DEFAULT_SPEC_DEVIATION_TOLERANCE_PCT = 5.00
WASTE_REGIMES: Tuple[str, ...] = ("BONDED", "DOMESTIC")

# ---------------------------------------------------------------------------
# Meal specification vocabulary (PRD §3.1)
# ---------------------------------------------------------------------------

CABINS: Tuple[str, ...] = ("FIRST", "BUSINESS", "ECONOMY")
MEAL_CODES: Tuple[str, ...] = ("STANDARD", "VGML", "AVML", "CHML", "GFML")
STORAGE_CLASSES: Tuple[str, ...] = ("CHILL", "HOT", "DRY")
HACCP_STEPS: Tuple[str, ...] = ("COOK_TEMP", "CHILL_DOWN", "HOLD_TEMP", "BLAST_CHILL")
DEFAULT_LOAD_FACTOR_PCT = 0.00
MAX_LOAD_FACTOR_PCT = 25.00

# ---------------------------------------------------------------------------
# The store-allocation waterfall (PRD §3.4)
# ---------------------------------------------------------------------------

# "the chill store holds 250 units, the hot store 120 units, and the dry store
# 400 units"
ZONE_CAPACITY: Dict[str, int] = {"CHILL": 250, "HOT": 120, "DRY": 400}

# "the hot store falls back to the chill store, the chill store falls back to
# the dry store, and the dry store has no fallback at all"
OVERFLOW_FALLBACK: Dict[str, str] = {"HOT": "CHILL", "CHILL": "DRY"}

# "24 hours for food whose primary store is the hot store, and 72 hours for food
# whose primary store is the chill store"
OVERFLOW_MIN_SHELF_LIFE_HOURS: Dict[str, int] = {"HOT": 24, "CHILL": 72}

# "4 hours for the hot store, 72 hours for the chill store, and 720 hours for
# the dry store"
ZONE_CUTOFF_HOURS: Dict[str, int] = {"HOT": 4, "CHILL": 72, "DRY": 720}

# "the flight's `revised_std_utc` pulled back by an hour and a half of slot
# preparation lead"
SLOT_PREP_LEAD_MINUTES = 90

# The visit order of the waterfall: hot store, then chill store, then dry store.
ZONE_VISIT_ORDER: Tuple[str, ...] = ("HOT", "CHILL", "DRY")

# ---------------------------------------------------------------------------
# HACCP verdict thresholds and risk weights (PRD §3.5)
# ---------------------------------------------------------------------------

COOK_TEMP_MIN_C = 75.0  # passes at or above
CHILL_DOWN_MAX_C = 8.0  # passes at or below
HOLD_TEMP_MAX_C = 5.0  # passes at or below
BLAST_CHILL_MAX_C = 3.0  # passes at or below

MEASURED_TEMP_MIN_C = -40.0
MEASURED_TEMP_MAX_C = 200.0

HACCP_FAIL_WEIGHT = 40.00
HACCP_REWORK_WEIGHT = 15.00
HACCP_RISK_SCORE_CAP = 100.00
HACCP_MAX_FAILS_BEFORE_REJECT = 2  # "the resulting failure count ... two or fewer"
HACCP_MAX_REWORK_ROUNDS = 2  # release requires strictly below two

# The release gates, in the pinned order of PRD §2.6 band 80.
RELEASE_GATE_ORDER: List[str] = [
    "ERR_HACCP_STEP_MISSING",
    "ERR_HACCP_HOLD_ACTIVE",
    "ERR_HACCP_REWORK_LIMIT",
    "ERR_RELEASE_DEADLINE_PASSED",
]

# ---------------------------------------------------------------------------
# Carts (PRD §3.6)
# ---------------------------------------------------------------------------

CART_TYPES: Tuple[str, ...] = ("STD_HALF", "STD_FULL", "OVEN_RACK", "DRY_BOX")
MIN_CART_CAPACITY_UNITS = 1
MAX_CART_CAPACITY_UNITS = 400

# ---------------------------------------------------------------------------
# Ramp resources and delivery windows (PRD §3.7)
# ---------------------------------------------------------------------------

DEFAULT_TRUCK_BUFFER_MINUTES = 20
MAX_TRUCK_BUFFER_MINUTES = 120
DEFAULT_MAX_CONCURRENT_RUNS = 2
MIN_MAX_CONCURRENT_RUNS = 1
MAX_MAX_CONCURRENT_RUNS = 6

# "opens five hours before `revised_std_utc` and closes forty-five minutes
# before it"
SLOT_BAND_EARLIEST_LEAD_MINUTES = 300
SLOT_BAND_LATEST_LEAD_MINUTES = 45

# "the logical clock to be at or after `window_start_utc` pulled back by one
# hour of dispatch lead"
DISPATCH_LEAD_MINUTES = 60

EVENT_DISPATCH = "DISPATCH"
EVENT_ARRIVE = "ARRIVE"
EVENT_DELIVER = "DELIVER"
EVENT_MISS = "MISS"

MISS_REASONS: Tuple[str, ...] = (
    "SLOT_LOST",
    "AIRCRAFT_NOT_READY",
    "TRAFFIC",
    "EQUIPMENT_FAILURE",
)

# "sets `penalty_cents` to a flat 750,000 cents"
MISSED_FLAT_PENALTY_CENTS = 750_000

# "the first thirty billable minutes at 250 cents each, the next thirty ... at
# 400 cents each, and every billable minute beyond the sixtieth at 600 cents"
LATENESS_BANDS: Tuple[Tuple[int, int], ...] = ((30, 250), (30, 400), (0, 600))

# ---------------------------------------------------------------------------
# Delays (PRD §3.8)
# ---------------------------------------------------------------------------

# "Only once the flight's cumulative `delay_minutes` has reached an hour and a
# half does the delay touch delivery runs at all."
DELAY_RESLOT_THRESHOLD_MINUTES = 90

# ---------------------------------------------------------------------------
# Money (PRD §3.9)
# ---------------------------------------------------------------------------

OVERHEAD_RATE = 0.12  # "one plus a twelve percent overhead rate"

# "nine percent for a net cost from 0 up to and including 199,999 cents, seven
# percent from 200,000 up to and including 499,999 cents, and five percent for
# 500,000 cents and above"
HANDLING_TIERS: Tuple[Tuple[int, int, float], ...] = (
    (0, 199_999, 0.09),
    (200_000, 499_999, 0.07),
    (500_000, None, 0.05),
)

DISPOSAL_METHODS: Tuple[str, ...] = ("INCINERATION", "RENDERING", "LANDFILL")
BONDED_DISPOSAL_METHODS: Tuple[str, ...] = ("INCINERATION",)

# "a deviation from 5.00 up to and including 9.99 is `MINOR`, from 10.00 up to
# and including 19.99 is `MAJOR`, and 20.00 or above is `CRITICAL`"
DEVIATION_SEVERITY_BANDS: Tuple[Tuple[float, str], ...] = (
    (20.00, "CRITICAL"),
    (10.00, "MAJOR"),
    (5.00, "MINOR"),
)

# ---------------------------------------------------------------------------
# The audit docket (PRD §3.10)
# ---------------------------------------------------------------------------

FINDING_TYPES: Tuple[str, ...] = (
    "SPEC_DEVIATION",
    "HACCP_BREACH",
    "SEAL_MISMATCH",
    "LATE_DELIVERY",
)
SEVERITIES: Tuple[str, ...] = ("MINOR", "MAJOR", "CRITICAL")

FINDING_BASE_CENTS: Dict[str, int] = {
    "SPEC_DEVIATION": 120_000,
    "HACCP_BREACH": 500_000,
    "SEAL_MISMATCH": 200_000,
    "LATE_DELIVERY": 80_000,
}
SEVERITY_MULTIPLIER: Dict[str, float] = {"MINOR": 1.0, "MAJOR": 2.5, "CRITICAL": 5.0}

# "When a finding creation pushes an airline's `open_finding_count` to three or
# more, the airline moves `ACTIVE → SUSPENDED`"
OPEN_FINDING_SUSPEND_THRESHOLD = 3

# ---------------------------------------------------------------------------
# The canonical reference data of the suite's service day
# ---------------------------------------------------------------------------

AIRLINE_AN = {
    "name": "AeroNordic",
    "iata_code": "AN",
    "waste_regime": "BONDED",
    "cost_cap_per_pax_cents": 6000,
}

SPEC_AN_F = {
    "spec_code": "AN-F-STD",
    "cabin": "FIRST",
    "meal_code": "STANDARD",
    "storage_class": "HOT",
    "portion_grams": 420,
    "gross_weight_grams": 900,
    "unit_cost_cents": 4200,
    "shelf_life_hours": 4,
    "required_haccp_steps": ["COOK_TEMP", "HOLD_TEMP"],
    "load_factor_pct": 0.00,
}
SPEC_AN_C = {
    "spec_code": "AN-C-STD",
    "cabin": "BUSINESS",
    "meal_code": "STANDARD",
    "storage_class": "HOT",
    "portion_grams": 380,
    "gross_weight_grams": 850,
    "unit_cost_cents": 3900,
    "shelf_life_hours": 4,
    "required_haccp_steps": ["COOK_TEMP", "HOLD_TEMP"],
    "load_factor_pct": 5.00,
}
SPEC_AN_Y = {
    "spec_code": "AN-Y-STD",
    "cabin": "ECONOMY",
    "meal_code": "STANDARD",
    "storage_class": "CHILL",
    "portion_grams": 320,
    "gross_weight_grams": 700,
    "unit_cost_cents": 1450,
    "shelf_life_hours": 72,
    "required_haccp_steps": ["CHILL_DOWN", "HOLD_TEMP"],
    "load_factor_pct": 2.50,
}
SPEC_AN_V = {
    "spec_code": "AN-Y-VGML",
    "cabin": "ECONOMY",
    "meal_code": "VGML",
    "storage_class": "CHILL",
    "portion_grams": 310,
    "gross_weight_grams": 690,
    "unit_cost_cents": 1650,
    "shelf_life_hours": 72,
    "required_haccp_steps": ["CHILL_DOWN", "HOLD_TEMP"],
    "load_factor_pct": 0.00,
}

STATION_CODE = "OSL"
TRUCK_REGISTRATION = "HL-101"
STAND_CODE = "A12"

FLIGHT_NUMBER = "AN411"
SERVICE_DATE = "2026-09-15"
STD_UTC = "2026-09-15T10:00:00Z"
TAIL_NUMBER = "LN-AAA"

# The `action` selectors of the three action-dispatched endpoints (PRD §3.3,
# §3.9, §3.10).
ACTION_CANCEL = "CANCEL"
ACTION_SUBSTITUTE = "SUBSTITUTE"
ACTION_SEAL = "SEAL"
ACTION_DISPOSE = "DISPOSE"
ACTION_REJECT = "REJECT"
ACTION_DISPUTE = "DISPUTE"
ACTION_ACCEPT = "ACCEPT"
ACTION_WITHDRAW = "WITHDRAW"

# Passing probe readings for the four steps, used by the production helpers.
PASSING_TEMPS: Dict[str, float] = {
    "COOK_TEMP": 80.0,
    "CHILL_DOWN": 6.0,
    "HOLD_TEMP": 4.0,
    "BLAST_CHILL": 2.0,
}
FAILING_TEMPS: Dict[str, float] = {
    "COOK_TEMP": 74.9,
    "CHILL_DOWN": 8.1,
    "HOLD_TEMP": 5.1,
    "BLAST_CHILL": 3.1,
}
