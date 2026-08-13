"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class JobStatus(str, Enum):
    ESTIMATING = "ESTIMATING"
    AWARDED = "AWARDED"
    FABRICATING = "FABRICATING"
    ERECTING = "ERECTING"
    COMPLETE = "COMPLETE"


class BillingBasis(str, Enum):
    WEIGHT = "WEIGHT"
    COUNT = "COUNT"


class ShopDrawingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MaterialGrade(str, Enum):
    A36 = "A36"
    A572 = "A572"
    A992 = "A992"


class MillBillingMode(str, Enum):
    NOMINAL = "NOMINAL"
    ACTUAL = "ACTUAL"


class MillOrderStatus(str, Enum):
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"


class ErectionSequenceStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    ERECTED = "ERECTED"


class PieceStatus(str, Enum):
    DETAILED = "DETAILED"
    IN_SHOP = "IN_SHOP"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    REWORK = "REWORK"
    INSPECTED = "INSPECTED"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    ERECTED = "ERECTED"


class WelderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WeldProcess(str, Enum):
    SMAW = "SMAW"
    FCAW = "FCAW"
    GMAW = "GMAW"


class WeldStatus(str, Enum):
    WELDED = "WELDED"
    VISUAL_PASSED = "VISUAL_PASSED"
    NDT_PASSED = "NDT_PASSED"
    VISUAL_REJECTED = "VISUAL_REJECTED"
    NDT_REJECTED = "NDT_REJECTED"


class InspectionKind(str, Enum):
    FINAL_PIECE = "FINAL_PIECE"
    WELD_VISUAL = "WELD_VISUAL"
    WELD_NDT = "WELD_NDT"
    AISC_AUDIT = "AISC_AUDIT"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class ShippingLoadStatus(str, Enum):
    STAGING = "STAGING"
    LOADING = "LOADING"
    SHIPPED = "SHIPPED"


class FieldFixStatus(str, Enum):
    PRICED = "PRICED"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"


class BackchargeStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class ProgressBillingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    FABRICATOR_ADMIN = "FABRICATOR_ADMIN"
    DETAILER = "DETAILER"
    EOR = "EOR"
    FOREMAN = "FOREMAN"
    WELDER = "WELDER"
    QC_INSPECTOR = "QC_INSPECTOR"
    GC_PM = "GC_PM"


# All resources carry id + created_at + updated_at + version (PRD section 2.4).

class Job(TypedDict, total=False):
    id: str
    name: str
    contract_value_cents: int
    billing_basis: str
    requires_aisc_hold: bool
    status: str
    total_weight_lbs: int
    erected_weight_lbs: int
    pct_complete: float
    billed_to_date_cents: int
    retainage_held_cents: int
    pending_backcharge_cents: int
    settled_backcharge_cents: int
    retainage_releasable_cents: int
    created_at: str
    updated_at: str
    version: int


class ShopDrawing(TypedDict, total=False):
    id: str
    job_id: str
    drawing_number: str
    revision: int
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MillOrder(TypedDict, total=False):
    id: str
    job_id: str
    material_grade: str
    ordered_weight_lbs: int
    unit_price_per_cwt_cents: int
    billing_mode: str
    received_weight_lbs: Optional[int]
    invoice_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ErectionSequence(TypedDict, total=False):
    id: str
    job_id: str
    seq_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Piece(TypedDict, total=False):
    id: str
    job_id: str
    piece_mark: str
    weight_lbs: int
    drawing_id: str
    sequence_id: str
    load_id: Optional[str]
    stale_revision: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Welder(TypedDict, total=False):
    id: str
    full_name: str
    qual_process: str
    qual_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Weld(TypedDict, total=False):
    id: str
    piece_id: str
    welder_id: str
    process: str
    weld_date: str
    window_start: str
    window_end: str
    repair_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    piece_id: Optional[str]
    weld_id: Optional[str]
    status: str
    inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShippingLoad(TypedDict, total=False):
    id: str
    job_id: str
    load_number: str
    laydown_slot: str
    delivery_date: str
    trailer_capacity_lbs: int
    total_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairLine(TypedDict):
    labor_hours: float
    labor_rate_cents: int
    material_cents: int


class FieldFix(TypedDict, total=False):
    id: str
    job_id: str
    piece_id: str
    description: str
    repair_lines: List[Any]
    amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Backcharge(TypedDict, total=False):
    id: str
    job_id: str
    field_fix_id: str
    amount_cents: int
    settled_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressBilling(TypedDict, total=False):
    id: str
    job_id: str
    period_label: str
    pct_complete_snapshot: float
    earned_cum_cents: int
    retainage_cum_cents: int
    retainage_booked_cents: int
    net_due_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
