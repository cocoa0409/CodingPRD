"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    PROJECT_MANAGER = "ProjectManager"
    FIELD_SUPERVISOR = "FieldSupervisor"
    SAFETY_MANAGER = "SafetyManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ENVIRONMENTAL_APPROVER = "EnvironmentalApprover"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_HOLD = "CREDIT_HOLD"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class JobType(str, Enum):
    VACUUM = "VACUUM"
    HYDROBLAST = "HYDROBLAST"
    COMBINED = "COMBINED"


class PricingMode(str, Enum):
    UNIT_RATE = "UNIT_RATE"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"


class ExecutionStatus(str, Enum):
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    MOBILIZED = "MOBILIZED"
    IN_PROGRESS = "IN_PROGRESS"
    FIELD_COMPLETE = "FIELD_COMPLETE"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SafetyStatus(str, Enum):
    CLEAR = "CLEAR"
    STOP_WORK = "STOP_WORK"


class Hazard(str, Enum):
    CONFINED_SPACE = "CONFINED_SPACE"
    HIGH_PRESSURE_WATER = "HIGH_PRESSURE_WATER"
    CHEMICAL_EXPOSURE = "CHEMICAL_EXPOSURE"
    SLIP_TRIP = "SLIP_TRIP"
    ERGONOMIC = "ERGONOMIC"
    OTHER = "OTHER"


class WaterSource(str, Enum):
    SITE_POTABLE = "SITE_POTABLE"
    SITE_NONPOTABLE = "SITE_NONPOTABLE"
    TRUCKED_IN = "TRUCKED_IN"


class JhaStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PermitType(str, Enum):
    CONFINED_SPACE = "CONFINED_SPACE"
    HOT_WORK = "HOT_WORK"
    LINE_BREAK = "LINE_BREAK"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class UnitType(str, Enum):
    VAC_TRUCK = "VAC_TRUCK"
    HYDROBLASTER = "HYDROBLASTER"
    COMBO = "COMBO"


class ResourceKind(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    OPERATOR = "OPERATOR"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class HazardClass(str, Enum):
    NON_HAZ = "NON_HAZ"
    HAZ = "HAZ"
    SPECIAL = "SPECIAL"


class VarianceBasis(str, Enum):
    VOLUME = "VOLUME"
    WEIGHT = "WEIGHT"


class WasteProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class FacilityPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    EXCEPTION = "EXCEPTION"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class ContainmentStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    DEFICIENT = "DEFICIENT"


class DowntimeCause(str, Enum):
    CUSTOMER_DELAY = "CUSTOMER_DELAY"
    WEATHER = "WEATHER"
    REGULATORY_HOLD = "REGULATORY_HOLD"
    SAFETY_STOP = "SAFETY_STOP"
    CONTRACTOR_FAULT = "CONTRACTOR_FAULT"


class DowntimeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    BILLED = "BILLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    MAJOR = "MAJOR"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry the common system fields
# (id, created_at, updated_at, version) per the PRD's global identity rules.
# ---------------------------------------------------------------------------


class Site(TypedDict, total=False):
    id: str
    name: str
    credit_status: str
    active_rate_schedule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    site_id: str
    label: str
    vacuum_per_gallon_cents: int
    hydroblast_per_foot_cents: int
    labor_rate_cents_per_hour: int
    equipment_rate_cents_per_hour: int
    standby_rate_cents_per_hour: int
    overtime_multiplier: float
    minimum_invoice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    site_id: str
    job_type: str
    pricing_mode: str
    description: str
    estimated_gallons: int
    pinned_rate_schedule_id: str
    execution_status: str
    safety_status: str
    gallons_removed: int
    feet_cleaned: int
    standby_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class JobHazardAnalysis(TypedDict, total=False):
    id: str
    job_id: str
    revision_number: int
    hazards: List[str]
    confined_space: bool
    max_operating_pressure_psi: Optional[int]
    planned_water_flow_gpm: Optional[float]
    water_source: Optional[str]
    submitted_by: Optional[str]
    approved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    job_id: str
    permit_type: str
    space_id: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    unit_code: str
    unit_type: str
    max_pressure_psi: int
    tank_capacity_gal: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    full_name: str
    employee_ref: str
    hazwoper_expires_on: str
    hydroblast_certified: bool
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    job_id: str
    resource_kind: str
    equipment_unit_id: Optional[str]
    operator_id: Optional[str]
    window_start: str
    window_end: str
    window_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteProfile(TypedDict, total=False):
    id: str
    site_id: str
    facility_id: str
    waste_code: str
    hazard_class: str
    density_lbs_per_gal: float
    disposal_rate_per_ton_cents: int
    variance_basis: str
    submitted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalFacility(TypedDict, total=False):
    id: str
    name: str
    epa_id: str
    total_capacity_tons: float
    reserved_tons: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class DisposalManifest(TypedDict, total=False):
    id: str
    job_id: str
    waste_profile_id: str
    estimated_gallons: int
    estimated_tons: Optional[float]
    received_tons: Optional[float]
    variance_pct: Optional[float]
    billed_tons: Optional[float]
    disposal_charge_cents: Optional[int]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContainmentRecord(TypedDict, total=False):
    id: str
    job_id: str
    sequence: int
    water_used_gallons: int
    water_captured_gallons: int
    capture_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict, total=False):
    id: str
    job_id: str
    cause: str
    started_at: str
    ended_at: Optional[str]
    closure_day: str
    duration_minutes: Optional[int]
    grace_minutes_applied: Optional[int]
    billable_minutes: Optional[int]
    billed_blocks: Optional[int]
    billed_amount_cents: Optional[int]
    invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    line_id: str
    kind: str
    description: str
    quantity: float
    unit: str
    rate_cents: int
    amount_cents: int
    discountable: bool
    voided: bool
    origin: str


class Invoice(TypedDict, total=False):
    id: str
    job_id: str
    invoice_number: str
    pricing_mode_snapshot: str
    lines: List[InvoiceLine]
    subtotal_cents: int
    discount_cents: int
    environmental_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    job_id: str
    severity: str
    title: str
    description: str
    osha_recordable: Optional[bool]
    corrective_action: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
