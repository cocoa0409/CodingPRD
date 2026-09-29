"""
Domain constants for the Berry Harvest Ops API test suite.

Every value here is transcribed from the PRD: the logical clock default of
section 2.5, the precision families of section 2.6, the variety tables of
section 3.3 and section 3.6, and the money constants of section 3.4 and
section 3.5.
"""

# ─── Namespace ────────────────────────────────────────────────────────────

BASE = "/berry-ops"

# ─── Logical clock (PRD 2.5) ──────────────────────────────────────────────

# "At service start-up the logical clock reads exactly `2026-08-01T00:00:00Z`."
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ─── Roles (PRD 2.1) ──────────────────────────────────────────────────────

ROLE_HARVEST_MANAGER = "HarvestManager"
ROLE_FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
ROLE_CREW_SUPERVISOR = "CrewSupervisor"
ROLE_PAYROLL_CLERK = "PayrollClerk"
ROLE_PACKHOUSE_OPERATOR = "PackhouseOperator"
ROLE_SALES_MANAGER = "SalesManager"
ROLE_PICKER = "Picker"

ALL_ROLES = (
    ROLE_HARVEST_MANAGER,
    ROLE_FOOD_SAFETY_OFFICER,
    ROLE_CREW_SUPERVISOR,
    ROLE_PAYROLL_CLERK,
    ROLE_PACKHOUSE_OPERATOR,
    ROLE_SALES_MANAGER,
    ROLE_PICKER,
)

# ─── Enumerations ─────────────────────────────────────────────────────────

VARIETIES = ("STRAWBERRY", "BLUEBERRY", "RASPBERRY", "BLACKBERRY")
LABOR_PROGRAMS = ("DOMESTIC", "H2A")
GRADES = ("A", "B", "CULL")

WATER_STATUSES = ("NO_SAMPLES", "PROVISIONAL", "COMPLIANT", "NON_COMPLIANT", "FAILED")
FOOD_SAFETY_POSTURES = ("RESTRICTED", "CLEARED", "QUARANTINED")
CREW_STATUSES = ("RECRUITING", "STAFFED", "CERTIFIED", "ACTIVE", "RELEASED")
WINDOW_STATUSES = ("PLANNED", "CONFIRMED", "OPEN", "SUSPENDED", "CLOSED", "CANCELLED")
SESSION_STATUSES = ("OPEN", "TALLIED", "APPROVED", "DISPUTED", "SETTLED", "VOIDED")
QUALITY_FLAGS = ("PENDING", "MEETS_STANDARD", "BELOW_STANDARD")
PAYROLL_STATUSES = ("DRAFT", "LOCKED", "SETTLED")
COLD_CHAIN_STATUSES = ("PACKED", "COOLING", "COOLED", "SHIPPED")
DISPOSITION_STATUSES = (
    "UNCOMMITTED",
    "RESERVED",
    "DELIVERED",
    "REJECTED",
    "REPACKED",
)
COMMITMENT_STATUSES = ("OPEN", "SETTLED", "DEFAULTED")
FILL_STATUSES = ("PENDING", "FILLED", "SHORTFALL")
RISK_FLAGS = ("ON_TRACK", "AT_RISK")
ALLOCATION_STATUSES = ("RESERVED", "SHIPPED", "RELEASED")

# ─── Water program (PRD 3.1) ──────────────────────────────────────────────

# "the single-sample maximum of 410 MPN per 100 mL"
SINGLE_SAMPLE_MAX_MPN = 410
# "the geometric-mean criterion of 126 MPN per 100 mL"
GEOMEAN_CRITERION_MPN = 126
# "only the **last five** rows of that ordering participate"
ROLLING_WINDOW_SIZE = 5
# "fewer than three samples are in the window, the status is `PROVISIONAL`"
PROVISIONAL_SAMPLE_FLOOR = 3
MPN_MIN = 1
MPN_MAX = 100000

QUARANTINE_REASON_SINGLE_SAMPLE = "SINGLE_SAMPLE_EXCEEDANCE"
SUSPENDED_REASON_BLOCK_QUARANTINE = "BLOCK_QUARANTINE"
VOID_REASON_WINDOW_SUSPENDED = "WINDOW_SUSPENDED"
DISPUTE_REASON_WINDOW_SUSPENDED = "WINDOW_SUSPENDED"
RELEASE_REASON_LOT_REJECTED = "LOT_REJECTED"

# ─── Crew (PRD 3.2) ───────────────────────────────────────────────────────

CREW_HEAD_COUNT_MIN = 1
CREW_HEAD_COUNT_MAX = 60
HYGIENE_TRAINING_VALIDITY_DAYS = 365

# ─── Harvest windows (PRD 3.3) ────────────────────────────────────────────

# "7.0 for `STRAWBERRY`, 10.0 for `BLUEBERRY`, 8.0 for `RASPBERRY` and 8.5 for
# `BLACKBERRY`"
MIN_BRIX = {
    "STRAWBERRY": 7.0,
    "BLUEBERRY": 10.0,
    "RASPBERRY": 8.0,
    "BLACKBERRY": 8.5,
}

# "9.0 for `STRAWBERRY`, 12.0 for `BLUEBERRY`, 10.0 for `RASPBERRY` and 10.5
# for `BLACKBERRY`"
TARGET_BRIX = {
    "STRAWBERRY": 9.0,
    "BLUEBERRY": 12.0,
    "RASPBERRY": 10.0,
    "BLACKBERRY": 10.5,
}

# "22 for `STRAWBERRY`, 18 for `BLUEBERRY`, 12 for `RASPBERRY` and 14 for
# `BLACKBERRY`"
BASE_PICK_RATE = {
    "STRAWBERRY": 22,
    "BLUEBERRY": 18,
    "RASPBERRY": 12,
    "BLACKBERRY": 14,
}

RIPE_MULTIPLIER = 1.10
UNRIPE_MULTIPLIER = 1.00
CREW_CAP = 60
REENTRY_BUFFER_HOURS = 12

FORECAST_BRIX_MIN = 0.0
FORECAST_BRIX_MAX = 30.0
PIECE_RATE_MIN = 1
PIECE_RATE_MAX = 500
CLAMSHELL_WEIGHT_MAX = 5

# ─── Pay (PRD 3.4, PRD 3.5) ───────────────────────────────────────────────

# "the statutory minimum of 1650 cents per hour"
MINIMUM_WAGE_CENTS_PER_HOUR = 1650
# "the maximum tolerated cull rate of 0.08"
MAX_CULL_RATE = 0.08
# "the window rate is derated by twenty percent"
BELOW_STANDARD_RATE_FACTOR = 0.80
# "the allowable daily charge of 900 cents"
HOUSING_DAILY_CAP_CENTS = 900
# "ten percent of `gross_cents` rounded **down**"
HOUSING_GROSS_SHARE = 0.10
# "a session that has already used its three permitted revisions"
TALLY_REVISION_CAP = 3
HOURS_WORKED_MAX = 16.00

# ─── Cold chain (PRD 3.6) ─────────────────────────────────────────────────

# "7 for `STRAWBERRY`, 14 for `BLUEBERRY`, 5 for `RASPBERRY` and 6 for
# `BLACKBERRY`"
SHELF_LIFE_BASE_DAYS = {
    "STRAWBERRY": 7,
    "BLUEBERRY": 14,
    "RASPBERRY": 5,
    "BLACKBERRY": 6,
}

# "subtracts 0 days for grade `A`, 1 for grade `B` and 3 for `CULL`"
GRADE_DERATE_DAYS = {"A": 0, "B": 1, "CULL": 3}

FIELD_DELAY_TOLERANCE_HOURS = 2.0
COOLING_TARGET_HOURS = 4.0
EXIT_TEMP_TARGET_F = 34.0
EXIT_TEMP_STEP_F = 2.0
SHELF_LIFE_FLOOR_DAYS = 1
REPACK_CHILD_DERATE_DAYS = 1

TUNNEL_SLOT_CAPACITY_MIN = 1
TUNNEL_SLOT_CAPACITY_MAX = 96
TARGET_PULP_TEMP_MIN_F = 30.0
TARGET_PULP_TEMP_MAX_F = 40.0
FIELD_PULP_TEMP_MIN_F = 30.0
FIELD_PULP_TEMP_MAX_F = 110.0

# ─── Buyer programs (PRD 3.7) ─────────────────────────────────────────────

PRICE_CENTS_PER_LB_MIN = 1
PRICE_CENTS_PER_LB_MAX = 10000
SHELF_LIFE_GUARANTEE_MIN_DAYS = 1
SHELF_LIFE_GUARANTEE_MAX_DAYS = 30
# "five percent per shortfall day, capped at thirty percent"
SHELF_LIFE_DISCOUNT_PER_DAY = 0.05
SHELF_LIFE_DISCOUNT_CAP = 0.30
# "the ninety-five percent fill target"
FILL_TARGET = 0.95
# "the three-day risk lead"
RISK_LEAD_DAYS = 3
# "fifteen percent of the contract value"
SHORTFALL_PENALTY_RATE = 0.15

# ─── Pagination (PRD 2.3) ─────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
