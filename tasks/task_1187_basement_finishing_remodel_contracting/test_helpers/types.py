"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACTOR = "Contractor"
    HOMEOWNER = "Homeowner"
    SUBCONTRACTOR = "Subcontractor"
    INSPECTOR = "Inspector"


class ProjectStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSMENT = "ASSESSMENT"
    DESIGN = "DESIGN"
    PERMITTING = "PERMITTING"
    SCHEDULING = "SCHEDULING"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssessmentKind(str, Enum):
    SCREENING = "SCREENING"
    VERIFICATION = "VERIFICATION"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class DesignPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class ChangeOrderKind(str, Enum):
    ADD = "ADD"
    CREDIT = "CREDIT"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class Trade(str, Enum):
    DEMOLITION = "DEMOLITION"
    FRAMING = "FRAMING"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    INSULATION = "INSULATION"
    DRYWALL = "DRYWALL"
    FLOORING = "FLOORING"
    PAINT = "PAINT"
    GENERAL = "GENERAL"


# Trades whose phases require a passed rough-in inspection before completion (PRD §3.6).
ROUGH_IN_TRADES = [Trade.PLUMBING.value, Trade.ELECTRICAL.value, Trade.HVAC.value]


class WorkPhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    ROUGH_IN = "ROUGH_IN"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class WarrantyClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PriceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# ---------------------------------------------------------------------------


class Contractor(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    created_at: str
    updated_at: str
    version: int


class Homeowner(TypedDict, total=False):
    id: str
    name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    name: str
    trade: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    homeowner_id: str
    contractor_id: str
    address: str
    basement_sqft: int
    base_contract_cents: int
    status: str
    strike_count: int
    last_resumed_at: Optional[str]
    contract_price_cents: int
    price_variant: str
    approved_design_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoistureAssessment(TypedDict, total=False):
    id: str
    project_id: str
    assessment_kind: str
    slab_moisture_lbs: float
    interior_rh_pct: float
    efflorescence_observed: bool
    grading_deficit: bool
    egress_windows_existing: int
    ceiling_height_in: float
    remediation_notes: Optional[str]
    moisture_risk_score: Optional[int]
    risk_band: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignPackage(TypedDict, total=False):
    id: str
    project_id: str
    layout_notes: str
    mechanical_relocations: List[Dict[str, Any]]
    revision_number: int
    revision_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    project_id: str
    bedroom_count: int
    windows: List[Dict[str, Any]]
    ceiling_height_in: float
    finished_area_sqft: int
    low_area_sqft: int
    prohibited_area_sqft: int
    pinned_design_id: str
    pinned_design_revision: int
    egress_compliant: Optional[bool]
    ceiling_compliant: Optional[bool]
    amendment_count: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllowanceLine(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    budgeted_cents: int
    reserved_cents: int
    drawn_cents: int
    selected: bool
    actual_cents: int
    remaining_cents: int
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    scope_description: str
    kind: str
    scope_items: List[Dict[str, Any]]
    allowance_draws: List[Dict[str, Any]]
    price_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkPhase(TypedDict, total=False):
    id: str
    project_id: str
    subcontractor_id: str
    trade: str
    zone: str
    start_date: str
    end_date: str
    crew_count: int
    predecessor_ids: List[str]
    requires_rough_in: bool
    pre_block_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DailySiteLog(TypedDict, total=False):
    # Immutable daily record (PRD §2.4): carries ONLY id + created_at among the
    # system-managed fields — no updated_at, no version.
    id: str
    created_at: str
    project_id: str
    subcontractor_id: str
    work_date: str
    containment_intact: bool
    hepa_run_hours: float
    noise_db_max: float
    cleanup_completed: bool
    violation: bool
    strike_applied: bool


class Inspection(TypedDict, total=False):
    id: str
    project_id: str
    work_phase_id: Optional[str]
    type: str
    result_notes: Optional[str]
    resulted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    project_id: str
    issued_at: str
    warranty_start: str
    warranty_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    project_id: str
    certificate_id: str
    description: str
    claimed_cents: int
    fresh_slab_moisture_lbs: float
    fresh_interior_rh_pct: float
    moisture_recurrence_confirmed: bool
    coverage_pct: float
    awarded_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
