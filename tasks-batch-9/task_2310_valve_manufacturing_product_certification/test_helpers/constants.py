"""
Domain constants for the Valve Manufacturing & Product Certification API.

Every value here is transcribed from the PRD: role names and header names (§2.1),
pagination limits (§2.3), the logical works clock origin (§2.5), rounding scales
(§2.6), the chemistry gate (§3.2), the standard test envelope (§3.4), the torque
sizing ladder (§3.5), the licensing thresholds (§3.6), and the engineered-order
pricing waterfall and documentation weights (§3.8).
"""

# ─── Routing ──────────────────────────────────────────

API_PREFIX = "/valve-mfg"

# ─── Roles (PRD §2.1) ─────────────────────────────────

ROLE_PRODUCT_ENGINEER = "ProductEngineer"
ROLE_PROCUREMENT_SPECIALIST = "ProcurementSpecialist"
ROLE_SUPPLIER_REP = "SupplierRep"
ROLE_TEST_TECHNICIAN = "TestTechnician"
ROLE_QUALITY_MANAGER = "QualityManager"
ROLE_MONOGRAM_AUDITOR = "MonogramAuditor"
ROLE_FIELD_SERVICE_COORDINATOR = "FieldServiceCoordinator"

ALL_ROLES = [
    ROLE_PRODUCT_ENGINEER,
    ROLE_PROCUREMENT_SPECIALIST,
    ROLE_SUPPLIER_REP,
    ROLE_TEST_TECHNICIAN,
    ROLE_QUALITY_MANAGER,
    ROLE_MONOGRAM_AUDITOR,
    ROLE_FIELD_SERVICE_COORDINATOR,
]

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# ─── Pagination (PRD §2.3) ────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── The logical works clock (PRD §2.5) ───────────────

FRESH_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Rounding scales (PRD §2.6) ───────────────────────

TORQUE_DECIMALS = 1
MARGIN_DECIMALS = 2
PRESSURE_DECIMALS = 1
MASS_DECIMALS = 3
INDEX_DECIMALS = 2
PCT_DECIMALS = 2

# ─── Design enumerations (PRD §3.1) ───────────────────

VALVE_TYPES = ["GATE", "BALL", "BUTTERFLY", "CONTROL"]
PRESSURE_CLASSES = [150, 300, 600, 900, 1500, 2500]
MATERIAL_GRADES = ["WCB", "CF8M", "LCC", "A105", "F316"]
SEAT_TYPES = ["SOFT", "METAL"]
SPECIAL_SERVICES = ["FIRE_SAFE", "CRYOGENIC", "FUGITIVE_EMISSION"]

# Type-test validity for the recomputed qualified_special_services list (PRD §3.1).
TYPE_TEST_VALIDITY_DAYS = 1825

# ─── Foundry quality index (PRD §3.2) ─────────────────

QUALITY_INDEX_CLEAN = 100.00
QUALITY_INDEX_RATE_WEIGHT = 40
QUALITY_INDEX_REVOKED_PENALTY = 8
QUALITY_INDEX_MIN = 0.00
QUALITY_INDEX_MAX = 100.00
FOUNDRY_ACTIVE_FLOOR = 80.00
FOUNDRY_PROBATION_FLOOR = 60.00

# ─── The chemistry gate (PRD §3.2) ────────────────────

CARBON_EQUIVALENT_CEILING = {
    "WCB": 0.45,
    "LCC": 0.43,
    "A105": 0.48,
    "CF8M": 0.40,
    "F316": 0.40,
}

IMPACT_ENERGY_FLOOR_J = {
    "WCB": 20,
    "LCC": 27,
    "A105": 20,
    "CF8M": 34,
    "F316": 34,
}

PROCESSES = ["CASTING", "FORGING"]
COMPONENT_TYPES = ["BODY", "BONNET", "BALL", "DISC", "STEM", "SEAT_RING"]

# ─── The standard test envelope (PRD §3.4) ────────────

RATED_PRESSURE_BAR = {
    150: 19.6,
    300: 51.1,
    600: 102.1,
    900: 153.2,
    1500: 255.3,
    2500: 425.5,
}

SHELL_PRESSURE_MULTIPLIER = 1.5
SEAT_PRESSURE_MULTIPLIER = 1.1

TEST_TYPES = ["SHELL", "SEAT", "FUNCTIONAL", "FIRE_SAFE", "CRYOGENIC", "FUGITIVE_EMISSION"]
DEFAULT_STANDARD_REF = "API-598"

# Hold-time bands over bore_size_mm; each band's upper edge belongs to that band.
HOLD_SECONDS_BANDS = [
    (50, 15),
    (150, 60),
    (300, 120),
]
HOLD_SECONDS_LARGEST_BORE = 300

# Emission leak classes banded on a parts-per-million figure.
EMISSION_CLASS_AA_CEILING = 50
EMISSION_CLASS_A_CEILING = 100
EMISSION_CLASS_B_CEILING = 500
EMISSION_CLASS_C_CEILING = 1000

# ─── Torque sizing (PRD §3.5) ─────────────────────────

QUARTER_TURN_TYPES = ["BALL", "BUTTERFLY"]
MULTI_TURN_TYPES = ["GATE", "CONTROL"]
QUARTER_TURN_DIVISOR = 10000
MULTI_TURN_DIVISOR = 20000

SERVICE_TORQUE_FACTOR = {
    "FIRE_SAFE": 1.25,
    "CRYOGENIC": 1.40,
    "FUGITIVE_EMISSION": 1.15,
}
NO_SERVICE_TORQUE_FACTOR = 1.00

SEAT_TORQUE_FACTOR = {
    "SOFT": 1.00,
    "METAL": 1.30,
}

CUSTOMER_STATED_ALLOWANCE = 1.10
VENDOR_MEASURED_ALLOWANCE = 1.00

# Safety margin tiers keyed on the already-rounded required torque.
MARGIN_TIER_LOW_CEILING = 500.0
MARGIN_TIER_HIGH_CEILING = 2000.0
MARGIN_BELOW_500 = 0.30
MARGIN_500_TO_2000 = 0.25
MARGIN_ABOVE_2000 = 0.20

ACTUATOR_TYPES = ["PNEUMATIC", "HYDRAULIC", "ELECTRIC"]
SIZING_BASES = ["CATALOG", "DATASHEET"]

# ─── Monogram licensing (PRD §3.6) ────────────────────

AUDIT_COOLING_OFF_DAYS = 30
CONDITIONAL_GRACE_DAYS = 180
FROZEN_OPEN_MAJOR_THRESHOLD = 2
CONDITIONAL_OPEN_MAJOR_COUNT = 1
CONDITIONAL_OPEN_MINOR_THRESHOLD = 5
GRANT_MAX_OPEN_MINOR = 4
GRANT_CONDITIONAL_MIN_OPEN_MINOR = 5

FINDING_SEVERITIES = ["MAJOR", "MINOR"]
FINDING_ENTRY_ACTIONS = ["RAISE", "CLOSE", "WAIVE"]

# ─── Engineered orders (PRD §3.8) ─────────────────────

MAX_CLARIFICATION_ROUNDS = 3

SURCHARGE_RATE = {
    "FIRE_SAFE": 0.06,
    "CRYOGENIC": 0.12,
    "FUGITIVE_EMISSION": 0.04,
}

VOLUME_DISCOUNT_HIGH_FLOOR = 6_000_000
VOLUME_DISCOUNT_HIGH_RATE = 0.06
VOLUME_DISCOUNT_LOW_FLOOR = 2_000_000
VOLUME_DISCOUNT_LOW_RATE = 0.03
VOLUME_DISCOUNT_NONE_RATE = 0.0

EXPEDITE_RATE = 0.08

CANCEL_RETENTION_FROM_APPROVED = 0.10
CANCEL_RETENTION_FROM_PRODUCTION = 0.35

DOC_TYPES = [
    "MATERIAL_TEST_REPORT",
    "TEST_CERTIFICATE",
    "DIMENSIONAL_REPORT",
    "NDE_REPORT",
    "ACTUATOR_DATASHEET",
    "DECLARATION_OF_CONFORMITY",
]

DOC_WEIGHT = {
    "MATERIAL_TEST_REPORT": 0.25,
    "TEST_CERTIFICATE": 0.25,
    "DIMENSIONAL_REPORT": 0.15,
    "NDE_REPORT": 0.15,
    "ACTUATOR_DATASHEET": 0.10,
    "DECLARATION_OF_CONFORMITY": 0.10,
}

DOC_TORQUE_SOURCES = ["CUSTOMER_STATED", "VENDOR_MEASURED"]

# ─── Decertification reasons (PRD §3.7) ───────────────

DECERTIFICATION_REASONS = [
    "MANUAL",
    "LOT_QUARANTINE",
    "LICENSE_SUSPENDED",
    "LICENSE_DENIED",
    "SPECIAL_SERVICE_REVOKED",
]

HELD_REASON_UNIT_DECERTIFIED = "UNIT_DECERTIFIED"
HELD_REASON_DOC_PACKAGE_VOIDED = "DOC_PACKAGE_VOIDED"
