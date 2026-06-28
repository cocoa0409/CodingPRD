"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD exactly. Entities that carry the full common-field
set (id, created_at, updated_at, version) are distinguished from the lean
append-only / catalog records (GeneratorModel, LoadAssessment, ExerciseLog),
which carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    SERVICE_MANAGER = "ServiceManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status enums ─────────────────────────────────────────────────────────────
class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SIZED = "SIZED"
    PERMITTED = "PERMITTED"
    INSTALLED = "INSTALLED"
    ACTIVATED = "ACTIVATED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SizingMethod(str, Enum):
    STAGGERED = "STAGGERED"
    FULL_LOAD = "FULL_LOAD"


class RegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    VOID = "VOID"


class MonitoringHealth(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class OperatingStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    SERVICE_DUE = "SERVICE_DUE"
    NON_COMPLIANT = "NON_COMPLIANT"
    DECOMMISSIONED = "DECOMMISSIONED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class PlanFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class WarrantyResolution(str, Enum):
    REPAIR_COVERED = "REPAIR_COVERED"
    PRORATED_REFUND = "PRORATED_REFUND"
    NO_FAULT_FOUND = "NO_FAULT_FOUND"


class RefundBasis(str, Enum):
    CALENDAR = "CALENDAR"
    USAGE = "USAGE"


class DispatchOrigin(str, Enum):
    WARRANTY = "WARRANTY"
    PAID = "PAID"
    RECALL = "RECALL"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RemediationStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version)─
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    service_address: str
    elevation_ft: int
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    license_no: str
    gas_certified: bool
    status: str
    open_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class GeneratorProject(TypedDict):
    id: str
    customer_id: str
    model_id: Optional[str]
    fuel_type: str
    status: str
    required_kw: Optional[float]
    sizing_method: str
    permit_number: Optional[str]
    permit_status: str
    fuel_hookup_verified: bool
    ats_amps: Optional[int]
    install_tech_id: Optional[str]
    unit_id: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    project_id: str
    customer_id: str
    model_id: str
    serial_no: str
    rated_kw: float
    fuel_type: str
    registration_status: str
    warranty_start: Optional[str]
    warranty_total_months: int
    warranty_status: str
    monitoring_enabled: bool
    monitoring_health: str
    compliance_score: int
    operating_status: str
    last_exercise_at: Optional[str]
    runtime_hours: float
    created_at: str
    updated_at: str
    version: int


class MaintenancePlan(TypedDict):
    id: str
    unit_id: str
    frequency: str
    monitoring_bundled: bool
    status: str
    annual_price_cents: int
    visits_per_year: int
    visits_completed_ytd: int
    next_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    plan_id: str
    unit_id: str
    scheduled_for: str
    assigned_tech_id: Optional[str]
    status: str
    performed_at: Optional[str]
    runtime_added_hours: float
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    unit_id: str
    description: str
    status: str
    resolution: Optional[str]
    refund_cents: int
    refund_basis: str
    dispatch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairDispatch(TypedDict):
    id: str
    unit_id: str
    origin: str
    warranty_claim_id: Optional[str]
    assigned_tech_id: Optional[str]
    status: str
    labor_cents: int
    parts_cents: int
    billable: bool
    invoice_total_cents: int
    resolved_by_tech_id: Optional[str]
    runtime_added_hours: float
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict):
    id: str
    model_id: str
    code: str
    severity: str
    status: str
    opened_at: Optional[str]
    remediation_window_days: int
    affected_unit_count: int
    remediated_count: int
    created_at: str
    updated_at: str
    version: int


class RecallRemediation(TypedDict):
    id: str
    campaign_id: str
    unit_id: str
    deadline_at: str
    status: str
    dispatch_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Lean records (common_fields: false → ONLY id + created_at) ──────────────
class GeneratorModel(TypedDict):
    id: str
    sku: str
    rated_kw: float
    fuel_types: List[str]
    unit_price_cents: int
    warranty_months: int
    active: bool
    created_at: str


class LoadAssessment(TypedDict):
    id: str
    project_id: str
    appliances: List[dict]
    method: str
    computed_required_kw: float
    peak_demand_w: int
    created_at: str


class ExerciseLog(TypedDict):
    id: str
    unit_id: str
    occurred_at: str
    result: str
    runtime_minutes: int
    created_at: str
