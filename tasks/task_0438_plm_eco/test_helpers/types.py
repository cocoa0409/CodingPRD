"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain carries id, created_at, updated_at, and version
(PRD 2.4 — "There are no immutable entities in this domain; all of them expose
updated_at and version.").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD 2.1) ---
class UserRole(str, Enum):
    DESIGNER = "Designer"
    CHANGE_ADMIN = "ChangeAdmin"
    APPROVER = "Approver"
    QUALITY_ENGINEER = "QualityEngineer"
    SUPPLIER_MANAGER = "SupplierManager"
    VIEWER = "Viewer"


# --- Status enums ---
class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class PartType(str, Enum):
    MAKE = "MAKE"
    BUY = "BUY"
    PHANTOM = "PHANTOM"


class RevisionLifecycle(str, Enum):
    WORKING = "WORKING"
    IN_REVIEW = "IN_REVIEW"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class DocumentLifecycle(str, Enum):
    WORKING = "WORKING"
    IN_REVIEW = "IN_REVIEW"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class ChangeRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_APPROVAL = "IN_APPROVAL"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeviationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class DefectCode(str, Enum):
    DIMENSIONAL = "DIMENSIONAL"
    COSMETIC = "COSMETIC"
    MATERIAL = "MATERIAL"
    FUNCTIONAL = "FUNCTIONAL"


class PcnStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class BuildStatus(str, Enum):
    PLANNED = "PLANNED"
    BUILT = "BUILT"
    SHIPPED = "SHIPPED"


class ConformanceStatus(str, Enum):
    CONFORMING = "CONFORMING"
    NONCONFORMING = "NONCONFORMING"
    WAIVED = "WAIVED"


class ReasonCode(str, Enum):
    DESIGN_DEFECT = "DESIGN_DEFECT"
    COST_REDUCTION = "COST_REDUCTION"
    SUPPLIER_CHANGE = "SUPPLIER_CHANGE"
    OBSOLESCENCE = "OBSOLESCENCE"


class DocType(str, Enum):
    CAD = "CAD"
    DRAWING = "DRAWING"
    SPEC = "SPEC"


# --- Entity TypedDicts (all common_fields: true) ---
class Supplier(TypedDict):
    id: str
    name: str
    supplier_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    part_number: str
    name: str
    part_type: str
    base_cost_cents: int
    default_supplier_id: Optional[str]
    released_revision_id: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class PartRevision(TypedDict):
    id: str
    part_id: str
    rev_label: str
    supersedes_revision_id: Optional[str]
    governing_change_order_id: Optional[str]
    lifecycle_state: str
    planned_cost_cents: int
    effective_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class BomLine(TypedDict):
    id: str
    parent_revision_id: str
    child_part_id: str
    quantity: int
    scrap_factor: float
    reference_designator: str
    created_at: str
    updated_at: str
    version: int


class EngineeringChangeRequest(TypedDict):
    id: str
    title: str
    affected_part_id: str
    reason_code: str
    source_pcn_id: Optional[str]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineeringChangeOrder(TypedDict):
    id: str
    change_request_id: str
    created_by_user_id: str
    required_approvals: int
    approval_count: int
    effectivity_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalTask(TypedDict):
    id: str
    change_order_id: str
    assignee_user_id: str
    decision: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeAffectedItem(TypedDict):
    id: str
    change_order_id: str
    part_revision_id: str
    pinned: bool
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict):
    id: str
    doc_number: str
    title: str
    doc_type: str
    part_id: Optional[str]
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class Deviation(TypedDict):
    id: str
    part_id: str
    change_order_id: Optional[str]
    defect_code: str
    max_units: int
    effective_from: str
    effective_to: str
    covered_unit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierChangeNotice(TypedDict):
    id: str
    supplier_id: str
    affected_part_id: str
    pcn_reference: str
    spawned_ecr_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SerializedUnit(TypedDict):
    id: str
    serial_number: str
    part_revision_id: str
    deviation_id: Optional[str]
    build_status: str
    conformance_status: str
    created_at: str
    updated_at: str
    version: int
