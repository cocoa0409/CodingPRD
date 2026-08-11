"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the uniform system-managed fields id, created_at,
updated_at and version (PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    CUSTOMER = "Customer"
    SUBCONTRACTOR = "Subcontractor"
    ANONYMOUS = "Anonymous"


class SubcontractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerKind(str, Enum):
    OWNER = "OWNER"
    ADJUSTER = "ADJUSTER"


class WindZone(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class IncidentType(str, Enum):
    FIRE = "FIRE"
    STORM = "STORM"
    VANDALISM = "VANDALISM"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class JobWorkStatus(str, Enum):
    INTAKE = "INTAKE"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    SECURED = "SECURED"
    BREACH_HOLD = "BREACH_HOLD"
    READY_FOR_REMOVAL = "READY_FOR_REMOVAL"
    REMOVED = "REMOVED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Hazard(str, Enum):
    COLLAPSE = "COLLAPSE"
    ELECTRICAL = "ELECTRICAL"
    GAS = "GAS"
    WATER = "WATER"
    ASBESTOS = "ASBESTOS"


class HazardLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    CLEARED = "CLEARED"
    SUPERSEDED = "SUPERSEDED"


class ScopeKind(str, Enum):
    BOARD = "BOARD"
    TARP = "TARP"
    FENCE = "FENCE"


class ScopeUnit(str, Enum):
    SHEETS = "SHEETS"
    SQFT = "SQFT"
    LINEAR_FT = "LINEAR_FT"


class ScopeItemStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    VOIDED = "VOIDED"


class ServiceKind(str, Enum):
    POWER = "POWER"
    LIGHTING = "LIGHTING"
    PATROL = "PATROL"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    MISSED = "MISSED"


class PermitKind(str, Enum):
    PERMIT = "PERMIT"
    NOTIFICATION = "NOTIFICATION"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ArtifactKind(str, Enum):
    PHOTO = "PHOTO"
    AUTHORIZATION = "AUTHORIZATION"
    MEASUREMENT_SHEET = "MEASUREMENT_SHEET"


class PackageStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"
    LOCKED = "LOCKED"
    AMENDED = "AMENDED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Market(TypedDict, total=False):
    id: str
    name: str
    code: str
    sla_minutes_p1: int
    sla_minutes_p2: int
    sla_minutes_p3: int
    permit_required: bool
    notification_required: bool
    notification_deadline_hours: int
    late_notification_fee_cents: int
    board_rate_per_sheet_cents: int
    tarp_rate_per_sqft_cents: int
    fence_rate_per_linear_ft_cents: int
    patrol_visit_fee_cents: int
    temp_power_daily_rate_cents: int
    temp_lighting_daily_rate_cents: int
    generator_pool_units: int
    removal_flat_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    legal_name: str
    status: str
    completed_job_count: int
    breached_job_count: int
    expired_offer_count: int
    active_assignment_count: int
    reliability_score_lenient: float
    reliability_score_strict: float
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict, total=False):
    id: str
    subcontractor_id: str
    market_id: str
    max_concurrent_jobs: int
    rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    kind: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    customer_id: str
    market_id: str
    address_line: str
    wind_zone: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    property_id: str
    customer_id: str
    incident_type: str
    priority: str
    sla_minutes: int
    reported_at: str
    dispatched_at: Optional[str]
    secured_at: Optional[str]
    work_status: str
    safety_cleared: bool
    compliance_breach: bool
    total_planned_sheets: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    job_id: str
    subcontractor_id: str
    offer_seq: int
    status: str
    offered_at: str
    offer_expires_at: str
    responded_at: Optional[str]
    arrived_at: Optional[str]
    response_minutes: Optional[int]
    sla_breach: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SafetyAssessment(TypedDict, total=False):
    id: str
    job_id: str
    assessor_subcontractor_id: str
    hazards: List[str]
    structural_risk_score: int
    hazard_level: str
    moderate_ppe_required: bool
    status: str
    mitigation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeItem(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    opening_count: Optional[int]
    width_in: Optional[float]
    height_in: Optional[float]
    door_count: int
    length_ft: Optional[float]
    width_ft: Optional[float]
    linear_ft: Optional[float]
    planned_qty: float
    unit: str
    actual_qty: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemporaryService(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    starts_at: str
    ends_at: str
    generator_units: int
    daily_rate_cents: int
    status: str
    deactivated_at: Optional[str]
    billable_days: Optional[int]
    service_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PatrolVisit(TypedDict, total=False):
    id: str
    temporary_service_id: str
    window_start: str
    window_end: str
    status: str
    checked_in_at: Optional[str]
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class PermitCase(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    status: str
    deadline_at: Optional[str]
    filed_at: Optional[str]
    confirmation_number: Optional[str]
    is_late: bool
    penalty_billed: bool
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentPackage(TypedDict, total=False):
    id: str
    job_id: str
    photo_count: int
    authorization_signed: bool
    measurement_sheet_recorded: bool
    required_photo_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    label: str
    quantity: float
    unit: str
    rate_cents: int
    multiplier: float
    line_cents: int


class Invoice(TypedDict, total=False):
    id: str
    job_id: str
    variant: str
    status: str
    lines: List[InvoiceLine]
    work_subtotal_cents: int
    service_subtotal_cents: int
    removal_fee_cents: int
    penalty_cents: int
    discount_cents: int
    pre_discount_total_cents: int
    total_cents: int
    submitted_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
