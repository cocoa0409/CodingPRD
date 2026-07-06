"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    BILLING_CLERK = "BillingClerk"


class ChimneyType(str, Enum):
    MASONRY = "MASONRY"
    PREFAB_METAL = "PREFAB_METAL"
    FACTORY_BUILT = "FACTORY_BUILT"


class ApplianceType(str, Enum):
    WOOD_STOVE = "WOOD_STOVE"
    OPEN_FIREPLACE = "OPEN_FIREPLACE"
    GAS_INSERT = "GAS_INSERT"
    PELLET = "PELLET"


class LinerType(str, Enum):
    NONE = "NONE"
    CLAY = "CLAY"
    STAINLESS = "STAINLESS"
    ALUMINUM = "ALUMINUM"


class DamperType(str, Enum):
    THROAT = "THROAT"
    TOP_MOUNT = "TOP_MOUNT"
    NONE = "NONE"


class CertLevel(str, Enum):
    CSIA_BASIC = "CSIA_BASIC"
    CSIA_ADVANCED = "CSIA_ADVANCED"
    MASTER = "MASTER"


class TripZone(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SafetyPosture(str, Enum):
    PENDING = "PENDING"
    SAFE = "SAFE"
    CONDITIONS = "CONDITIONS"
    UNSAFE = "UNSAFE"
    CONDEMNED = "CONDEMNED"


class FlueAssessment(str, Enum):
    UNASSESSED = "UNASSESSED"
    PASS = "PASS"
    DEFECTS = "DEFECTS"
    BLOCKED = "BLOCKED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SafetyOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONS = "CONDITIONS"
    FAIL = "FAIL"
    CONDEMN = "CONDEMN"


class RepairType(str, Enum):
    CAP = "CAP"
    LINER = "LINER"
    DAMPER = "DAMPER"
    GAS_LOG_CONVERSION = "GAS_LOG_CONVERSION"


class RepairStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CoverageType(str, Enum):
    LABOR_ONLY = "LABOR_ONLY"
    PARTS_INCLUSIVE = "PARTS_INCLUSIVE"


class WarrantyStatus(str, Enum):
    ISSUED = "ISSUED"
    CLAIMED = "CLAIMED"
    VOIDED = "VOIDED"


class ReminderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


# --- Entity TypedDicts ---
# Full-common-field entities carry id + created_at + updated_at + version.

class Customer(TypedDict):
    id: str
    name: str
    service_address: str
    phone: str
    email: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chimney(TypedDict):
    id: str
    customer_id: str
    chimney_type: str
    appliance_type: str
    flue_count: int
    cap_installed: bool
    liner_type: str
    damper_type: str
    last_service_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    cert_level: str
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict):
    id: str
    technician_id: str
    service_date: str
    window_start_ts: int
    window_end_ts: int
    capacity_minutes: int
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class ServiceJob(TypedDict):
    id: str
    customer_id: str
    chimney_id: str
    inspection_level: int
    expected_creosote_class: int
    trip_zone: str
    repair_authorization_cents: int
    job_status: str
    safety_posture: str
    flue_assessment: str
    sweep_provisional_cost_cents: int
    sweep_final_cost_cents: Optional[int]
    committed_cost_cents: int
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    route_day_id: str
    service_job_id: str
    technician_id: str
    start_ts: int
    end_ts: int
    on_site_minutes: int
    status: str
    no_show_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    service_job_id: str
    repair_type: str
    part_sku: Optional[str]
    quoted_cost_cents: int
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    labor_cents: Optional[int]
    parts_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    repair_order_id: str
    service_job_id: str
    coverage_type: str
    term_months: int
    issued_at: str
    covered_labor_cents: int
    covered_parts_cents: int
    status: str
    claimed_repair_type: Optional[str]
    last_claim_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReminderSchedule(TypedDict):
    id: str
    customer_id: str
    chimney_id: str
    cadence_months: int
    next_due_date: str
    status: str
    acknowledged_count: int
    is_due: bool
    created_at: str
    updated_at: str
    version: int


# Append-only measurement logs carry ONLY id + created_at (PRD §2.4).

class SweepLog(TypedDict):
    id: str
    service_job_id: str
    measured_creosote_class: int
    glaze_present: bool
    billed_cost_cents: int
    created_at: str


class SafetyCheck(TypedDict):
    id: str
    service_job_id: str
    co_ppm: int
    draft_ok: bool
    spillage_detected: bool
    outcome: str
    created_at: str
