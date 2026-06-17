"""Domain types: entity TypedDicts, status enums, role enum.

All types derive from the Sign Fabrication & Installation PRD. Every entity in
this system carries the common fields id, created_at, updated_at, and version
(PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────────

class SignProjectPhase(str, Enum):
    DESIGN = "DESIGN"
    ESTIMATING = "ESTIMATING"
    PERMITTING = "PERMITTING"
    FABRICATION = "FABRICATION"
    INSTALL = "INSTALL"
    WARRANTY = "WARRANTY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ArtProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class SiteSurveyStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class FabricationWorkOrderStatus(str, Enum):
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QC_HOLD = "QC_HOLD"
    READY_FOR_INSTALL = "READY_FOR_INSTALL"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ReorderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# ─── Domain value enums ──────────────────────────────────────────────────────

class JurisdictionCode(str, Enum):
    CITY_A = "CITY_A"
    CITY_B = "CITY_B"
    COUNTY_C = "COUNTY_C"


class SignType(str, Enum):
    MONUMENT = "MONUMENT"
    PYLON = "PYLON"
    WALL = "WALL"
    BLADE = "BLADE"


class Substrate(str, Enum):
    ALUMINUM = "ALUMINUM"
    ACRYLIC = "ACRYLIC"
    STEEL = "STEEL"


class PermitKind(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    ELECTRICAL = "ELECTRICAL"


class EquipmentClass(str, Enum):
    LADDER = "LADDER"
    BUCKET_TRUCK = "BUCKET_TRUCK"


class RequiredEquipmentClass(str, Enum):
    NONE = "NONE"
    LADDER = "LADDER"
    BUCKET_TRUCK = "BUCKET_TRUCK"


class DefectKind(str, Enum):
    ELECTRICAL = "ELECTRICAL"
    STRUCTURAL = "STRUCTURAL"
    COSMETIC = "COSMETIC"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    DESIGNER = "Designer"
    CUSTOMER = "Customer"
    SURVEYOR = "Surveyor"
    PERMIT_CLERK = "PermitClerk"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────

class SignProject(TypedDict):
    id: str
    customer_name: str
    site_address: str
    jurisdiction_code: str
    sign_type: str
    face_width_in: float
    face_height_in: float
    placement_height_ft: float
    illuminated: bool
    rush: bool
    phase: str
    approved_estimate_id: Optional[str]
    permit_required: bool
    contract_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ArtProof(TypedDict):
    id: str
    sign_project_id: str
    revision_no: int
    artwork_uri: str
    color_count: int
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    sign_project_id: str
    art_proof_id: str
    substrate: str
    material_rate_cents_per_sqft: int
    area_sqft: float
    material_cost_cents: int
    labor_cost_cents: int
    subtotal_cents: int
    surcharge_cents: int
    total_cents: int
    status: str
    valid_until_iso: str
    created_at: str
    updated_at: str
    version: int


class SiteSurvey(TypedDict):
    id: str
    sign_project_id: str
    measured_clearance_ft: float
    overhead_obstruction: bool
    ground_bearing_ok: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    sign_project_id: str
    permit_kind: str
    fee_cents: int
    status: str
    expires_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FabricationWorkOrder(TypedDict):
    id: str
    sign_project_id: str
    estimate_id: str
    snapshot_total_cents: int
    status: str
    qc_pass: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    sign_project_id: str
    work_order_id: str
    crew_id: str
    equipment_id: Optional[str]
    required_equipment_class: str
    window_start_iso: str
    window_end_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    certified_aerial: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    asset_tag: str
    equipment_class: str
    max_reach_ft: float
    in_service: bool
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    sign_project_id: str
    reason: str
    new_face_width_in: Optional[float]
    new_face_height_in: Optional[float]
    new_substrate: Optional[str]
    delta_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    sign_project_id: str
    install_job_id: str
    defect_kind: str
    reported_iso: str
    covered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Reorder(TypedDict):
    id: str
    sign_project_id: str
    reorder_project_id: Optional[str]
    quantity: int
    reprice: bool
    status: str
    created_at: str
    updated_at: str
    version: int
