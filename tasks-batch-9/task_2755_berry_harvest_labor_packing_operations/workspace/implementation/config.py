"""Domain constants for the Berry Harvest Ops API.

Every constant here traces to SCAFFOLD.yaml `calculations[].constants` and to the
matching prose in PRD.md §2.6 / §3.
"""

from decimal import Decimal

API_PREFIX = "/berry-ops"

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
VARIETIES = ("STRAWBERRY", "BLUEBERRY", "RASPBERRY", "BLACKBERRY")
LABOR_PROGRAMS = ("DOMESTIC", "H2A")
GRADES = ("A", "B", "CULL")

WATER_STATUSES = ("NO_SAMPLES", "PROVISIONAL", "COMPLIANT", "NON_COMPLIANT", "FAILED")
POSTURES = ("CLEARED", "RESTRICTED", "QUARANTINED")

CREW_STATUSES = ("RECRUITING", "STAFFED", "CERTIFIED", "ACTIVE", "RELEASED")
WINDOW_STATUSES = ("PLANNED", "CONFIRMED", "OPEN", "SUSPENDED", "CLOSED", "CANCELLED")
SESSION_STATUSES = ("OPEN", "TALLIED", "DISPUTED", "APPROVED", "SETTLED", "VOIDED")
QUALITY_FLAGS = ("PENDING", "MEETS_STANDARD", "BELOW_STANDARD")
PAYROLL_STATUSES = ("DRAFT", "LOCKED", "SETTLED")
COLD_CHAIN_STATUSES = ("PACKED", "COOLING", "COOLED", "SHIPPED")
DISPOSITION_STATUSES = ("UNCOMMITTED", "RESERVED", "DELIVERED", "REJECTED", "REPACKED")
COMMITMENT_STATUSES = ("OPEN", "SETTLED", "DEFAULTED")
FILL_STATUSES = ("PENDING", "FILLED", "SHORTFALL")
RISK_FLAGS = ("ON_TRACK", "AT_RISK")
ALLOCATION_STATUSES = ("RESERVED", "SHIPPED", "RELEASED")

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# water_quality_status (SCAFFOLD calculations.water_quality_status)
# ---------------------------------------------------------------------------
SINGLE_SAMPLE_MAX_MPN = 410
GEOMEAN_LIMIT_MPN = Decimal("126")
WATER_SAMPLE_WINDOW = 5
MIN_SAMPLES_FOR_COMPLIANT = 3

# ---------------------------------------------------------------------------
# window_crew_requirement
# ---------------------------------------------------------------------------
VARIETY_PICK_RATE = {
    "STRAWBERRY": Decimal("22"),
    "BLUEBERRY": Decimal("18"),
    "RASPBERRY": Decimal("12"),
    "BLACKBERRY": Decimal("14"),
}
BRIX_MIN = {
    "STRAWBERRY": Decimal("7.0"),
    "BLUEBERRY": Decimal("10.0"),
    "RASPBERRY": Decimal("8.0"),
    "BLACKBERRY": Decimal("8.5"),
}
BRIX_TARGET = {
    "STRAWBERRY": Decimal("9.0"),
    "BLUEBERRY": Decimal("12.0"),
    "RASPBERRY": Decimal("10.0"),
    "BLACKBERRY": Decimal("10.5"),
}
RIPE_MULTIPLIER = Decimal("1.10")
MIN_PICKER_FLOOR = 1
CREW_CAP = 60

# ---------------------------------------------------------------------------
# session_pay_per_session / payroll_period_averaged_settlement
# ---------------------------------------------------------------------------
MIN_WAGE_CENTS_PER_HOUR = Decimal("1650")
MAX_CULL_RATE = Decimal("0.08")
QUALITY_DERATE_PCT = Decimal("0.20")
HOUSING_DAILY_DEDUCTION_CENTS = 900
DEDUCTION_GROSS_CAP_PCT = Decimal("0.10")
MAX_TALLY_REVISIONS = 3

# ---------------------------------------------------------------------------
# Picker hygiene
# ---------------------------------------------------------------------------
HYGIENE_VALID_DAYS = 365

# ---------------------------------------------------------------------------
# lot_shelf_life
# ---------------------------------------------------------------------------
VARIETY_BASE_SHELF_LIFE = {
    "STRAWBERRY": 7,
    "BLUEBERRY": 14,
    "RASPBERRY": 5,
    "BLACKBERRY": 6,
}
GRADE_DERATE = {"A": 0, "B": 1, "CULL": 3}
FIELD_HEAT_MAX_HOURS = Decimal("2.0")
TARGET_COOL_HOURS = Decimal("4.0")
EXIT_TEMP_TARGET_F = Decimal("34.0")
EXIT_TEMP_STEP_F = Decimal("2.0")
SHELF_LIFE_FLOOR_DAYS = 1
REPACK_DERATE_DAYS = 1

# ---------------------------------------------------------------------------
# block_window_separation
# ---------------------------------------------------------------------------
BLOCK_REENTRY_BUFFER_HOURS = 12

# ---------------------------------------------------------------------------
# commitment_settlement
# ---------------------------------------------------------------------------
FILL_TARGET_PCT = Decimal("0.95")
SHORTFALL_PENALTY_RATE = Decimal("0.15")
SHELF_LIFE_DISCOUNT_PER_DAY = Decimal("0.05")
SHELF_LIFE_DISCOUNT_CAP_PCT = Decimal("0.30")
RISK_LEAD_DAYS = 3

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Cascade reason codes
REASON_BLOCK_QUARANTINE = "BLOCK_QUARANTINE"
REASON_WINDOW_SUSPENDED = "WINDOW_SUSPENDED"
REASON_SINGLE_SAMPLE_EXCEEDANCE = "SINGLE_SAMPLE_EXCEEDANCE"
REASON_LOT_REJECTED = "LOT_REJECTED"
