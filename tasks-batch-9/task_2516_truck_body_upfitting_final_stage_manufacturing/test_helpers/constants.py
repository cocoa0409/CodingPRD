"""Domain constants for the Truck Body Upfitting & Final Stage Manufacturing API.

Every value here is transcribed from the PRD: the role names of §2.1, the
pagination defaults of §2.3, the pinned logical-clock origin of §2.4, the
enumerations of §2.7, and the numeric tables of §3.6, §3.8 and §3.9.
"""

# --------------------------------------------------------------------------
# Routing (§2.2 / §4)
# --------------------------------------------------------------------------
API_PREFIX = "/upfit"
CLOCK_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Roles (§2.1)
# --------------------------------------------------------------------------
ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_PRODUCTION_SCHEDULER = "ProductionScheduler"
ROLE_UPFIT_ENGINEER = "UpfitEngineer"
ROLE_INSTALL_TECHNICIAN = "InstallTechnician"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
ROLE_CUSTOMER = "Customer"

ALL_STAFF_ROLES = (
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_SCHEDULER,
    ROLE_UPFIT_ENGINEER,
    ROLE_INSTALL_TECHNICIAN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_WARRANTY_ADMINISTRATOR,
)
ALL_ROLES = ALL_STAFF_ROLES + (ROLE_CUSTOMER,)

# Opaque operator identifiers (§2.1: not tied to any persisted entity).
USER_ADMIN = "adm-1"
USER_SCHEDULER = "ps-1"
USER_SCHEDULER_ALT = "ps-2"
USER_ENGINEER = "eng-1"
USER_TECHNICIAN = "tech-1"
USER_OFFICER = "co-1"
USER_OFFICER_ALT = "co-2"
USER_WARRANTY = "wa-1"

# --------------------------------------------------------------------------
# Logical clock (§2.4)
# --------------------------------------------------------------------------
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"
CLOCK_ORIGIN_DATE = "2026-08-01"

# --------------------------------------------------------------------------
# Pagination (§2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Enumerations (§2.7)
# --------------------------------------------------------------------------
BUILD_STATUSES = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "IN_BUILD",
    "BUILD_COMPLETE",
    "DELIVERED",
    "CHASSIS_HOLD",
    "CANCELLED",
)
COMPLIANCE_STATUSES = ("NOT_STARTED", "DESIGN_CERTIFIED", "MEASURED_CERTIFIED", "LABELED")
BODY_INSTALL_STATUSES = ("PLANNED", "INSTALLED")
CHASSIS_STATUSES = (
    "RECEIVED",
    "INSPECTED",
    "QUARANTINED",
    "ALLOCATED",
    "IN_UPFIT",
    "COMPLETED",
    "RETURNED",
)
INSTALLATION_STATUSES = ("PLANNED", "INSTALLED", "COMMISSIONED", "REMOVED")
INTERFACE_STATUSES = ("PROPOSED", "APPROVED", "REJECTED", "SUPERSEDED")
SLOT_STATUSES = ("QUEUED", "SCHEDULED", "IN_BUILD", "CLOSED", "CANCELLED")
CERTIFICATION_STATUSES = ("DRAFT", "APPROVED", "VOIDED")
CLAIM_STATUSES = ("SUBMITTED", "INSPECTED", "ADJUDICATED", "DISPUTED", "PAID")
CONFIG_STATUSES = ("DRAFT", "PUBLISHED", "DEPRECATED")
BAY_STATUSES = ("ACTIVE", "DOWN")

BODY_TYPES = ("SERVICE", "DUMP", "FLATBED", "VAN")
EQUIPMENT_CLASSES = ("CRANE", "LIFTGATE", "PTO_HOIST", "PTO_PUMP")
MOUNT_ZONES = ("BEHIND_CAB", "BODY_FLOOR", "REAR_OVERHANG")
ELECTRICAL_BUSES = ("J1939_CAN", "DISCRETE")
PTO_PROVISIONS = ("NONE", "CLUTCH_SHIFT", "FULL")
OWNERSHIPS = ("POOL_STOCK", "CUSTOMER_ASSIGNED")
STANDARDIZATION_TIERS = ("TIER_A", "TIER_B", "CUSTOM")
ORDER_TYPES = ("POOL_STOCK", "CUSTOMER_SPECIFIC")
WARRANTY_POSTURES = ("INTACT", "CONDITIONAL", "VOIDED")
HYDRAULIC_CIRCUITS = ("NONE", "PRIMARY", "SECONDARY")
HYDRAULIC_STATUSES = ("NOT_APPLICABLE", "OK", "DEFICIT")
INTERFACE_METHODS = ("BODY_BUILDER_MODULE", "CAN_GATEWAY", "DIRECT_SPLICE")
SIGNAL_SOURCES = ("BODY_CONTROLLER", "J1939_BUS", "DISCRETE_CIRCUIT")
WARRANTY_IMPACTS = ("NONE", "CONDITIONAL", "VOIDS")
SLOT_TYPES = ("BODY_MOUNT", "EQUIPMENT_INTEGRATION", "FINAL_QC")
CERTIFICATION_BASES = ("AS_DESIGNED", "AS_MEASURED")
LABEL_TYPES = ("FINAL_STAGE", "ALTERER", "INCOMPLETE_PASSTHROUGH")
RESPONSIBLE_PARTIES = ("UPFITTER", "CHASSIS_MANUFACTURER")
FAILURE_SYSTEMS = (
    "CHASSIS_ENGINE",
    "CHASSIS_TRANSMISSION",
    "CHASSIS_BRAKES",
    "CHASSIS_ELECTRICAL",
    "BODY_STRUCTURE",
    "BODY_ELECTRICAL",
    "HYDRAULICS",
)
SPLIT_BASES = ("PROVISIONAL", "FINAL")
VOIDED_REASONS = ("COMPONENT_SET_CHANGED", "BODY_MOUNT_CHANGED", "SUPERSEDED_BY_NEWER_DRAFT")

# --------------------------------------------------------------------------
# Pricing and scheduling tables (§3.6)
# --------------------------------------------------------------------------
SHOP_RATE_CENTS_PER_HOUR = 11500
LABOR_HOURS_BY_BODY_TYPE = {"SERVICE": 18, "DUMP": 14, "FLATBED": 10, "VAN": 22}
BASE_BUILD_DAYS_BY_BODY_TYPE = {"SERVICE": 21, "DUMP": 18, "FLATBED": 12, "VAN": 25}
DAYS_PER_HYDRAULIC_ITEM = 5
DAYS_PER_NON_HYDRAULIC_ITEM = 2
DISCOUNT_PCT_BY_TIER = {"TIER_A": 8, "TIER_B": 4, "CUSTOM": 0}
FEE_TIER_LOW_CENTS = 45000       # discounted subtotal strictly below 2_000_000
FEE_TIER_MID_CENTS = 72500       # discounted subtotal strictly below 4_000_000
FEE_TIER_HIGH_CENTS = 98000      # at or above 4_000_000
FEE_TIER_LOW_BOUND_CENTS = 2000000
FEE_TIER_MID_BOUND_CENTS = 4000000

# --------------------------------------------------------------------------
# Warranty tables (§3.9)
# --------------------------------------------------------------------------
BASE_SPLIT_BY_FAILURE_SYSTEM = {
    "CHASSIS_ENGINE": (95, 0, 5),
    "CHASSIS_TRANSMISSION": (95, 0, 5),
    "CHASSIS_BRAKES": (95, 0, 5),
    "CHASSIS_ELECTRICAL": (60, 35, 5),
    "BODY_STRUCTURE": (0, 95, 5),
    "BODY_ELECTRICAL": (0, 95, 5),
    "HYDRAULICS": (0, 95, 5),
}
TAINT_SHIFT_MAX_POINTS = 45
TAINT_SHIFT_ELIGIBLE_SYSTEMS = (
    "CHASSIS_ENGINE",
    "CHASSIS_TRANSMISSION",
    "CHASSIS_BRAKES",
    "CHASSIS_ELECTRICAL",
)
DEFAULT_WARRANTY_LIABILITY_CAP_CENTS = 5000000

# --------------------------------------------------------------------------
# Warranty impact table (§3.5)
# --------------------------------------------------------------------------
WARRANTY_IMPACT_TABLE = {
    ("BODY_BUILDER_MODULE", "J1939_CAN"): "NONE",
    ("BODY_BUILDER_MODULE", "DISCRETE"): "NONE",
    ("CAN_GATEWAY", "J1939_CAN"): "CONDITIONAL",
    ("CAN_GATEWAY", "DISCRETE"): "NONE",
    ("DIRECT_SPLICE", "J1939_CAN"): "VOIDS",
    ("DIRECT_SPLICE", "DISCRETE"): "CONDITIONAL",
}

# --------------------------------------------------------------------------
# Reference catalog rows reused across the suite
# --------------------------------------------------------------------------
CM_F550 = {
    "code": "F550-DRW-84CA",
    "make": "FORD",
    "gvwr_lb": 19500,
    "front_gawr_lb": 7000,
    "rear_gawr_lb": 14706,
    "wheelbase_in": 200,
    "cab_to_axle_in": 84,
    "curb_front_axle_lb": 4820,
    "curb_rear_axle_lb": 2680,
    "max_aux_amp_draw": 60,
    "electrical_bus": "J1939_CAN",
    "pto_provision": "FULL",
    "pto_max_flow_gpm": 18,
    "body_builder_book_rev": "BBB-2026.1",
    "incomplete_vehicle_document_rev": "IVD-2026.1",
}
CM_F450 = {
    "code": "F450-SRW-60CA",
    "make": "FORD",
    "gvwr_lb": 14000,
    "front_gawr_lb": 5000,
    "rear_gawr_lb": 9450,
    "wheelbase_in": 176,
    "cab_to_axle_in": 60,
    "curb_front_axle_lb": 4180,
    "curb_rear_axle_lb": 2320,
    "max_aux_amp_draw": 40,
    "electrical_bus": "DISCRETE",
    "pto_provision": "FULL",
    "pto_max_flow_gpm": 14,
    "body_builder_book_rev": "BBB-2026.1",
    "incomplete_vehicle_document_rev": "IVD-2026.1",
}
CM_F350_NO_PTO = {
    "code": "F350-SRW-60CA-NOPTO",
    "make": "FORD",
    "gvwr_lb": 14000,
    "front_gawr_lb": 5000,
    "rear_gawr_lb": 9450,
    "wheelbase_in": 176,
    "cab_to_axle_in": 60,
    "curb_front_axle_lb": 4180,
    "curb_rear_axle_lb": 2320,
    "max_aux_amp_draw": 40,
    "electrical_bus": "DISCRETE",
    "pto_provision": "NONE",
    "pto_max_flow_gpm": 0,
    "body_builder_book_rev": "BBB-2026.1",
    "incomplete_vehicle_document_rev": "IVD-2026.1",
}

BODY_SERVICE_11FT = {
    "code": "SERVICE-11FT",
    "body_type": "SERVICE",
    "weight_lb": 2100,
    "cg_from_body_front_in": 62,
    "cargo_cg_from_body_front_in": 66,
    "length_in": 132,
    "required_min_ca_in": 84,
    "required_min_wheelbase_in": 189,
    "aux_amp_draw": 12,
    "requires_hydraulics": False,
    "list_price_cents": 1450000,
}
BODY_DUMP_12FT = {
    "code": "DUMP-12FT",
    "body_type": "DUMP",
    "weight_lb": 3400,
    "cg_from_body_front_in": 78,
    "cargo_cg_from_body_front_in": 84,
    "length_in": 144,
    "required_min_ca_in": 60,
    "required_min_wheelbase_in": 176,
    "aux_amp_draw": 8,
    "requires_hydraulics": True,
    "list_price_cents": 1120000,
}
BODY_DUMP_16FT_HD = {
    "code": "DUMP-16FT-HD",
    "body_type": "DUMP",
    "weight_lb": 6200,
    "cg_from_body_front_in": 96,
    "cargo_cg_from_body_front_in": 100,
    "length_in": 192,
    "required_min_ca_in": 60,
    "required_min_wheelbase_in": 176,
    "aux_amp_draw": 8,
    "requires_hydraulics": True,
    "list_price_cents": 1750000,
}
BODY_VAN_BOX_14FT = {
    "code": "VAN-BOX-14FT",
    "body_type": "VAN",
    "weight_lb": 2900,
    "cg_from_body_front_in": 84,
    "cargo_cg_from_body_front_in": 86,
    "length_in": 168,
    "required_min_ca_in": 60,
    "required_min_wheelbase_in": 176,
    "aux_amp_draw": 14,
    "requires_hydraulics": False,
    "list_price_cents": 1900000,
}

EQ_CRANE_6000 = {
    "code": "CRANE-6000",
    "equipment_class": "CRANE",
    "weight_lb": 1250,
    "requires_pto": True,
    "required_flow_gpm": 8,
    "aux_amp_draw": 10,
    "duty_priority": 1,
    "mount_zone": "BEHIND_CAB",
    "requires_can_gateway": False,
    "list_price_cents": 780000,
}
EQ_LIFTGATE_2500 = {
    "code": "LIFTGATE-2500",
    "equipment_class": "LIFTGATE",
    "weight_lb": 780,
    "requires_pto": False,
    "required_flow_gpm": 0,
    "aux_amp_draw": 30,
    "duty_priority": 3,
    "mount_zone": "REAR_OVERHANG",
    "requires_can_gateway": False,
    "list_price_cents": 320000,
}
EQ_DUMP_HOIST_10T = {
    "code": "DUMP-HOIST-10T",
    "equipment_class": "PTO_HOIST",
    "weight_lb": 950,
    "requires_pto": True,
    "required_flow_gpm": 12,
    "aux_amp_draw": 5,
    "duty_priority": 2,
    "mount_zone": "BODY_FLOOR",
    "requires_can_gateway": False,
    "list_price_cents": 640000,
}
EQ_PTO_PUMP_AUX = {
    "code": "PTO-PUMP-AUX",
    "equipment_class": "PTO_PUMP",
    "weight_lb": 120,
    "requires_pto": True,
    "required_flow_gpm": 6,
    "aux_amp_draw": 4,
    "duty_priority": 4,
    "mount_zone": "BODY_FLOOR",
    "requires_can_gateway": False,
    "list_price_cents": 145000,
}

WORK_BAY_1 = {
    "code": "BAY-1",
    "concurrent_capacity": 1,
    "supported_body_types": ["SERVICE", "DUMP", "FLATBED", "VAN"],
}
CUSTOMER_METRO = {
    "name": "Metro Fleet Services",
    "account_code": "MFS-001",
    "fleet_contact_email": "fleet@metro.example",
}

# Deterministic 404 probes (RFC-4122 shaped, never minted by the server).
UNKNOWN_UUIDS = [f"00000000-0000-4000-8000-0000000000{i:02x}" for i in range(1, 16)]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000404"


# --------------------------------------------------------------------------
# VIN generators (§3.2 requires exactly 17 characters, unique across chassis)
# --------------------------------------------------------------------------
def vin_f550(serial: int) -> str:
    """A 17-character VIN in the F550 series."""
    return f"1FDUF5HT0CC3{serial:05d}"


def vin_f450(serial: int) -> str:
    """A 17-character VIN in the F450 series."""
    return f"1FDUF4HT0DD4{serial:05d}"
