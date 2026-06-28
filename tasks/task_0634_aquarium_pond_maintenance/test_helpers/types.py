"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    FIELD_TECH = "FieldTech"
    DISPATCHER = "Dispatcher"
    CUSTOMER_OWNER = "CustomerOwner"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SystemStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class StockingPosture(str, Enum):
    NORMAL = "NORMAL"
    OVERSTOCKED = "OVERSTOCKED"


class LivestockStatus(str, Enum):
    ALIVE = "ALIVE"
    QUARANTINED = "QUARANTINED"
    DECEASED = "DECEASED"


class EquipmentStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class VisitKind(str, Enum):
    ROUTINE = "ROUTINE"
    EMERGENCY = "EMERGENCY"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceSourceKind(str, Enum):
    VISIT = "VISIT"
    INSTALL = "INSTALL"
    EMERGENCY_TRIP = "EMERGENCY_TRIP"


class InstallStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_BUILD = "IN_BUILD"
    HANDED_OFF = "HANDED_OFF"
    CANCELLED = "CANCELLED"


class EmergencyStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    REPORTED = "REPORTED"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_PARTS = "AWAITING_PARTS"
    CLOSED = "CLOSED"
    SCRAPPED = "SCRAPPED"


class QuarantineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    ABORTED = "ABORTED"


class FeedingPlanStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SystemKind(str, Enum):
    REEF = "REEF"
    FRESHWATER = "FRESHWATER"
    POND = "POND"
    PALUDARIUM = "PALUDARIUM"


class SpeciesClass(str, Enum):
    COMMUNITY = "COMMUNITY"
    CICHLID = "CICHLID"
    GOLDFISH = "GOLDFISH"
    PREDATOR = "PREDATOR"
    INVERT = "INVERT"


class DeviceKind(str, Enum):
    FILTER = "FILTER"
    PUMP = "PUMP"
    HEATER = "HEATER"
    UV_STERILIZER = "UV_STERILIZER"
    SKIMMER = "SKIMMER"


class WaterParameter(str, Enum):
    ALKALINITY = "ALKALINITY"
    NITRATE = "NITRATE"
    PHOSPHATE = "PHOSPHATE"
    PH = "PH"
    AMMONIA = "AMMONIA"


class Severity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ServiceTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class RouteDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true -> id, created_at, updated_at, version
# common_fields: false (WaterTest) -> only id, created_at
# ---------------------------------------------------------------------------
class ServiceContract(TypedDict):
    id: str
    customer_name: str
    customer_user_id: str
    service_tier: str
    status: str
    route_day: str
    account_balance_cents: int
    alive_livestock_count: int
    created_at: str
    updated_at: str
    version: int


class SystemProfile(TypedDict):
    id: str
    contract_id: str
    label: str
    system_kind: str
    nominal_volume_l: float
    substrate_displacement_pct: float
    status: str
    bioload_index: float
    stocking_posture: str
    created_at: str
    updated_at: str
    version: int


class Livestock(TypedDict):
    id: str
    system_id: str
    common_name: str
    species_class: str
    adult_length_cm: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    system_id: str
    device_kind: str
    media_interval_days: int
    last_serviced_on: Optional[str]
    media_due_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    tech_user_id: str
    full_name: str
    certified_for_reef: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    system_id: str
    technician_id: str
    visit_kind: str
    emergency_call_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    labor_minutes: int
    status: str
    total_cents: int
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable reading
class WaterTest(TypedDict):
    id: str
    visit_id: str
    parameter: str
    measured_value: float
    target_value: float
    product_strength_ppm_per_ml: float
    recommended_dose_ml: float
    created_at: str


class Invoice(TypedDict):
    id: str
    contract_id: str
    source_kind: str
    source_id: str
    total_cents: int
    amount_paid_cents: int
    status: str
    due_on: str
    created_at: str
    updated_at: str
    version: int


class InstallProject(TypedDict):
    id: str
    contract_id: str
    system_id: str
    labor_estimate_cents: int
    equipment_estimate_cents: int
    actual_labor_minutes: int
    actual_equipment_cents: int
    change_order_cents: int
    quote_total_cents: int
    deposit_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyCall(TypedDict):
    id: str
    system_id: str
    severity: str
    reported_at: str
    trip_fee_cents: int
    status: str
    dispatched_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    equipment_id: str
    reported_symptom: str
    parts_needed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarantineRecord(TypedDict):
    id: str
    livestock_id: str
    quarantine_tank_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VacationFeedingPlan(TypedDict):
    id: str
    system_id: str
    window_start: str
    window_end: str
    feedings_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int
