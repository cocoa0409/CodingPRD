"""Every literal PRD.md fixes for this API, in one place.

Nothing here is invented: each value is quoted from PRD.md so tests can assert
against a named constant instead of a magic number, and so a change in the
contract shows up as one edit here rather than dozens across the suite.
"""

from decimal import Decimal

# ----------------------------------------------------------------------
# Roles (PRD.md section 2.1)
# ----------------------------------------------------------------------
ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_RESIN_TECHNICIAN = "ResinTechnician"
ROLE_MOLDING_OPERATOR = "MoldingOperator"
ROLE_ASSEMBLY_TECHNICIAN = "AssemblyTechnician"
ROLE_QUALITY_INSPECTOR = "QualityInspector"
ROLE_LOGISTICS_PLANNER = "LogisticsPlanner"
ROLE_WARRANTY_AGENT = "WarrantyAgent"
ROLE_CUSTOMER = "Customer"

ALL_ROLES: tuple[str, ...] = (
    ROLE_PLANT_ADMIN,
    ROLE_RESIN_TECHNICIAN,
    ROLE_MOLDING_OPERATOR,
    ROLE_ASSEMBLY_TECHNICIAN,
    ROLE_QUALITY_INSPECTOR,
    ROLE_LOGISTICS_PLANNER,
    ROLE_WARRANTY_AGENT,
    ROLE_CUSTOMER,
)

# The four roles whose X-User-ID must be a Technician id whose role_code matches.
TECHNICIAN_ROLE_CODES: dict[str, str] = {
    ROLE_RESIN_TECHNICIAN: "RESIN_TECH",
    ROLE_MOLDING_OPERATOR: "MOLDING_OPERATOR",
    ROLE_ASSEMBLY_TECHNICIAN: "ASSEMBLY_TECH",
    ROLE_QUALITY_INSPECTOR: "QUALITY_INSPECTOR",
}

# Certifications PRD.md requires before a technician may act.
CERT_RESIN_BLENDING = "RESIN_BLENDING"
CERT_FIXTURE_ASSEMBLY = "FIXTURE_ASSEMBLY"
CERT_WALL_GAUGE = "WALL_GAUGE"
CERT_IMPACT_RIG = "IMPACT_RIG"

REQUIRED_CERTIFICATIONS: dict[str, tuple[str, ...]] = {
    "RESIN_TECH": (CERT_RESIN_BLENDING,),
    "MOLDING_OPERATOR": (),
    "ASSEMBLY_TECH": (CERT_FIXTURE_ASSEMBLY,),
    "QUALITY_INSPECTOR": (CERT_WALL_GAUGE, CERT_IMPACT_RIG),
}

# ----------------------------------------------------------------------
# Logical clock (PRD.md section 2.5)
# ----------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# ----------------------------------------------------------------------
# Pagination (PRD.md section 2.3)
# ----------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ----------------------------------------------------------------------
# Enumerations, exactly as PRD.md section 2.8 lists them
# ----------------------------------------------------------------------
HULL_TYPES: tuple[str, ...] = ("KAYAK", "CANOE")
SIZE_CLASSES: tuple[str, ...] = ("COMPACT", "MID", "TANDEM", "OVERSIZE")
RESIN_GRADES: tuple[str, ...] = ("HDPE_LINEAR", "HDPE_XL", "MDPE")
COOLING_MODES: tuple[str, ...] = ("AMBIENT", "FORCED_AIR", "WATER_MIST")
AIRFLOW_MODES: tuple[str, ...] = ("AMBIENT", "FORCED_AIR", "WATER_MIST")
CERTIFICATIONS: tuple[str, ...] = (
    CERT_RESIN_BLENDING,
    CERT_FIXTURE_ASSEMBLY,
    CERT_WALL_GAUGE,
    CERT_IMPACT_RIG,
)
WARRANTY_BASES: tuple[str, ...] = ("PRO_RATA_AGE", "FLAT_SCHEDULE")
CLAIM_TYPES: tuple[str, ...] = ("HULL_DEFORMATION", "HARDWARE", "COSMETIC")
DESTINATION_ZONES: tuple[str, ...] = ("Z1", "Z2", "Z3")
COSMETIC_GRADES: tuple[str, ...] = ("A", "B", "C", "REJECT")

MOLD_STATUSES: tuple[str, ...] = ("AVAILABLE", "IN_CYCLE", "MAINTENANCE", "RETIRED")
EQUIPMENT_STATUSES: tuple[str, ...] = ("OPERATIONAL", "DOWN")
TECHNICIAN_STATUSES: tuple[str, ...] = ("ACTIVE", "SUSPENDED")
CUSTOMER_STATUSES: tuple[str, ...] = ("ACTIVE", "SUSPENDED")
WAREHOUSE_POSTURES: tuple[str, ...] = ("NORMAL", "RESTRICTED", "FROZEN")
RESIN_LOT_STATUSES: tuple[str, ...] = (
    "AVAILABLE",
    "DEPLETED",
    "QUARANTINED",
    "EXPIRED",
)
RESIN_CHARGE_STATUSES: tuple[str, ...] = ("RESERVED", "CONSUMED", "RELEASED")
RELEASED_REASONS: tuple[str, ...] = (
    "CYCLE_ABORTED",
    "LOT_QUARANTINED",
    "LOT_EXPIRED",
    "ORDER_CANCELLED",
    "STATION_DOWN",
    "MOLD_SERVICE_DUE",
)
PRODUCTION_ORDER_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "READY_TO_SCHEDULE",
    "BLOCKED_RESIN",
    "BLOCKED_WAREHOUSE",
    "IN_PRODUCTION",
    "COMPLETE",
    "CANCELLED",
)
BLOCKED_REASONS: tuple[str, ...] = ("NO_QUALIFIED_RESIN_LOT", "WAREHOUSE_FROZEN")
MOLDING_CYCLE_STATUSES: tuple[str, ...] = (
    "SCHEDULED",
    "OVEN_RUNNING",
    "COOLING",
    "DEMOLDED",
    "ABORTED",
)
ABORT_REASONS: tuple[str, ...] = (
    "OPERATOR_ABORT",
    "LOT_QUARANTINED",
    "LOT_EXPIRED",
    "ORDER_CANCELLED",
    "STATION_DOWN",
    "BAY_DOWN",
    "MOLD_SERVICE_DUE",
)
BUILD_STATUSES: tuple[str, ...] = (
    "DEMOLDED",
    "TRIMMED",
    "OUTFITTED",
    "SELLABLE",
    "REWORK",
    "SCRAPPED",
)
LOGISTICS_STATUSES: tuple[str, ...] = (
    "UNALLOCATED",
    "STORED",
    "LOADED",
    "IN_TRANSIT",
    "DELIVERED",
)
INSPECTION_VERDICTS: tuple[str, ...] = ("PENDING", "PASS", "REWORK", "SCRAP")
SHIPMENT_STATUSES: tuple[str, ...] = (
    "PLANNED",
    "LOADING",
    "SEALED",
    "IN_TRANSIT",
    "DELIVERED",
    "CANCELLED",
)
SHIPMENT_LINE_STATUSES: tuple[str, ...] = ("LOADED", "REMOVED")
CLAIM_STATUSES: tuple[str, ...] = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "DENIED",
    "WITHDRAWN",
    "VOIDED",
)
STORAGE_REVIEW_STATUSES: tuple[str, ...] = (
    "NOT_STARTED",
    "GUIDANCE_VERIFIED",
    "GUIDANCE_VIOLATED",
    "WAIVED",
)
# The two values POST /warranty-claims/{id}/storage-review accepts as outcome.
STORAGE_REVIEW_OUTCOMES: tuple[str, ...] = ("VERIFIED", "VIOLATED")
DENIAL_REASONS: tuple[str, ...] = (
    "STORAGE_GUIDANCE_VIOLATED",
    "NOT_A_MANUFACTURING_DEFECT",
    "TERM_EXPIRED",
    "APPROVAL_VOIDED",
)

# ----------------------------------------------------------------------
# Decimal scales PRD.md section 2.4 declares, by field family
# ----------------------------------------------------------------------
SCALE_MASS_KG = 3
SCALE_CUBE_M3 = 4
SCALE_NEST_FACTOR = 4
SCALE_PERCENT = 2
SCALE_WALL_THICKNESS_MM = 2
SCALE_WALL_STATS_MM = 3
SCALE_OVEN_TEMP_C = 1
SCALE_WARPAGE_INDEX = 3
SCALE_DENSITY = 3

# Handy Decimal quantisation targets for the scales above.
Q_MASS = Decimal("0.001")
Q_CUBE = Decimal("0.0001")
Q_PERCENT = Decimal("0.01")
Q_WARPAGE = Decimal("0.001")
Q_TEMP = Decimal("0.1")

# ----------------------------------------------------------------------
# Mould selection and size classes (PRD.md section 3.4)
# ----------------------------------------------------------------------
SIZE_CLASS_ORDER: dict[str, int] = {
    "COMPACT": 1,
    "MID": 2,
    "TANDEM": 3,
    "OVERSIZE": 4,
}

# ----------------------------------------------------------------------
# Wall thickness statistics (PRD.md section 3.6)
# ----------------------------------------------------------------------
MIN_MEASUREMENT_POINTS = 6
# The standard deviation divides by the number of points, not by n - 1.
SD_DIVISOR = "population_n"

# ----------------------------------------------------------------------
# Warpage index, provisional and final variants (PRD.md sections 3.5, 3.6)
# ----------------------------------------------------------------------
OVEN_TEMP_REFERENCE_C = Decimal("288")
OVEN_TEMP_SPAN_C = Decimal("40")
IDEAL_ROTATION_RATIO = Decimal("4.0")
W_THERMAL = Decimal("0.40")
W_COOLING = Decimal("0.35")
W_ROTATION = Decimal("0.25")
W_DISTRIBUTION = Decimal("0.50")
WARPAGE_INDEX_FLOOR = Decimal("0.000")
WARPAGE_INDEX_CEILING = Decimal("5.000")
SIZE_CLASS_WARPAGE_FACTOR: dict[str, Decimal] = {
    "COMPACT": Decimal("0.850"),
    "MID": Decimal("1.000"),
    "TANDEM": Decimal("1.150"),
    "OVERSIZE": Decimal("1.400"),
}
COOLING_MODE_WARPAGE_FACTOR: dict[str, Decimal] = {
    "AMBIENT": Decimal("1.000"),
    "FORCED_AIR": Decimal("0.900"),
    "WATER_MIST": Decimal("1.250"),
}

# ----------------------------------------------------------------------
# Inspection verdict thresholds (PRD.md section 3.6)
# ----------------------------------------------------------------------
WARPAGE_SCRAP_THRESHOLD = Decimal("2.500")
WARPAGE_REWORK_THRESHOLD = Decimal("1.200")
MAX_REWORK_COUNT = 2
DEFORMATION_THRESHOLD_MM = Decimal("3.00")

# ----------------------------------------------------------------------
# Production order cost overheads (PRD.md section 3.7)
# ----------------------------------------------------------------------
OVERHEAD_TIERS: tuple[tuple[int, Decimal], ...] = (
    (500000, Decimal("18.00")),
    (2000000, Decimal("14.50")),
)
OVERHEAD_TOP_RATE_PCT = Decimal("11.00")

# ----------------------------------------------------------------------
# Warehouse posture (PRD.md section 3.7)
# ----------------------------------------------------------------------
DEFAULT_RESTRICTED_THRESHOLD_PCT = Decimal("85.00")
DEFAULT_FROZEN_THRESHOLD_PCT = Decimal("95.00")
# Posture flips at or above the threshold, never strictly above it.
THRESHOLD_COMPARISON = "greater_than_or_equal_triggers"

# ----------------------------------------------------------------------
# Seasonal build-ahead quota (PRD.md section 3.7)
# ----------------------------------------------------------------------
DEFAULT_BUILD_AHEAD_CAP_PCT = Decimal("60.00")
MAX_OVERBUILD_FACTOR = Decimal("1.20")
CAP_ROUNDING = "floor"

# ----------------------------------------------------------------------
# Freight, quoted and billed variants (PRD.md section 3.8)
# ----------------------------------------------------------------------
DIM_FACTOR_KG_PER_M3 = Decimal("120.000")
ZONE_RATE_CENTS_PER_KG: dict[str, int] = {"Z1": 42, "Z2": 61, "Z3": 88}
UTILIZATION_DISCOUNT_TIERS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("90.00"), Decimal("12.00")),
    (Decimal("75.00"), Decimal("7.50")),
    (Decimal("60.00"), Decimal("3.00")),
)
FUEL_SURCHARGE_PCT = Decimal("9.50")
MIN_SEAL_UTILIZATION_PCT = Decimal("60.00")

# ----------------------------------------------------------------------
# Warranty payout (PRD.md section 3.9)
# ----------------------------------------------------------------------
WARRANTY_TERM_MONTHS = 60
CLAIM_TYPE_FACTOR: dict[str, Decimal] = {
    "HULL_DEFORMATION": Decimal("1.00"),
    "HARDWARE": Decimal("0.60"),
    "COSMETIC": Decimal("0.30"),
}
FLAT_SCHEDULE_BANDS: tuple[tuple[int, Decimal], ...] = (
    (12, Decimal("80.00")),
    (36, Decimal("50.00")),
    (60, Decimal("25.00")),
)
ADMIN_FEE_TIERS: tuple[tuple[int, Decimal], ...] = (
    (50000, Decimal("12.00")),
    (200000, Decimal("8.00")),
)
ADMIN_FEE_TOP_RATE_PCT = Decimal("5.00")
STORAGE_WAIVED_DEDUCTION_PCT = Decimal("35.00")
MONTHS_ROUNDING = "floor_complete_months"

# ----------------------------------------------------------------------
# Interval and counter conventions (PRD.md sections 2.9, 3.3)
# ----------------------------------------------------------------------
# Elapsed oven and cooling minutes are always floored to whole minutes.
MINUTE_ROUNDING = "floor"
OVEN_OCCUPANCY_MODE = "exclusive_per_arm"
OVEN_BOUNDARY = "half_open_with_symmetric_buffer"
COOLING_OCCUPANCY_MODE = "aggregate_slot_capacity"
COOLING_BOUNDARY = "closed_no_buffer"
SERVICE_COMPARISON = "greater_than_or_equal_triggers"
SERVICE_RESET = "to_zero"

# Cycle statuses that count as occupying an oven arm or a mould.
OVEN_OCCUPYING_STATUSES: tuple[str, ...] = ("SCHEDULED", "OVEN_RUNNING")
MOLD_OCCUPYING_STATUSES: tuple[str, ...] = ("SCHEDULED", "OVEN_RUNNING", "COOLING")
COOLING_OCCUPYING_STATUSES: tuple[str, ...] = (
    "SCHEDULED",
    "OVEN_RUNNING",
    "COOLING",
)

# ----------------------------------------------------------------------
# Ledger invariants and serials
# ----------------------------------------------------------------------
MASS_INVARIANT = "available_kg + reserved_kg + consumed_kg == received_kg"
RESERVE_INVARIANT = (
    "warranty_reserve_cents + warranty_paid_cents == initial_warranty_reserve_cents"
)
SERIAL_FORMAT = "<order_code>-<cavity_index:2>-<build_seq:4>"

# Units whose stored cube counts against a site's committed cube.
COMMITTED_LOGISTICS_STATUSES: tuple[str, ...] = ("STORED", "LOADED")
