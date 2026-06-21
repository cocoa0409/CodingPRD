"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD: every mutable resource carries id, created_at,
updated_at, version; the immutable Customer identity record carries only
id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    ESTIMATOR = "Estimator"
    FIELD_TECH = "FieldTech"
    PERMIT_CLERK = "PermitClerk"
    CUSTOMER = "Customer"


# --- Status enums ---
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    MEASURED = "MEASURED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitClearance(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class JobType(str, Enum):
    FENCE = "FENCE"
    DECK = "DECK"
    FENCE_AND_DECK = "FENCE_AND_DECK"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class WorkType(str, Enum):
    FENCE = "FENCE"
    DECK = "DECK"


class Material(str, Enum):
    CEDAR = "CEDAR"
    VINYL = "VINYL"
    COMPOSITE = "COMPOSITE"
    PT_PINE = "PT_PINE"
    ALUMINUM = "ALUMINUM"


class Style(str, Enum):
    PRIVACY = "PRIVACY"
    PICKET = "PICKET"
    DECK_STANDARD = "DECK_STANDARD"
    ORNAMENTAL = "ORNAMENTAL"


class Accessory(str, Enum):
    NONE = "NONE"
    SINGLE_GATE = "SINGLE_GATE"
    DOUBLE_GATE = "DOUBLE_GATE"
    STAIR_SET = "STAIR_SET"


class SiteMeasureStatus(str, Enum):
    RECORDED = "RECORDED"
    APPROVED = "APPROVED"


class PermitType(str, Enum):
    FENCE_PERMIT = "FENCE_PERMIT"
    DECK_PERMIT = "DECK_PERMIT"
    ZONING_VARIANCE = "ZONING_VARIANCE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"


class HoaApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MaterialOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CrewBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DrawMilestone(str, Enum):
    DEPOSIT = "DEPOSIT"
    DELIVERY = "DELIVERY"
    FRAMING = "FRAMING"
    FINAL = "FINAL"


class DrawStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class WarrantyStatus(str, Enum):
    ISSUED = "ISSUED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


# --- Entity TypedDicts ---

# Customer: immutable identity record — id + created_at only, no version/updated_at.
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    hoa_governed: bool
    created_at: str


class Project(TypedDict):
    id: str
    customer_id: str
    site_address: str
    job_type: str
    status: str
    active_estimate_id: Optional[str]
    contract_total: float
    draws_paid_total: float
    balance_due: float
    permit_clearance: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    project_id: str
    status: str
    tax_rate_pct: float
    material_subtotal: float
    labor_subtotal: float
    material_tax: float
    contract_total: float
    reconciled_total: Optional[float]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    estimate_id: str
    work_type: str
    material: str
    style: str
    quantity_units: float
    accessory: str
    grade_slope_pct: float
    line_material_cost: float
    created_at: str
    updated_at: str
    version: int


class SiteMeasure(TypedDict):
    id: str
    project_id: str
    status: str
    measured_quantities: List[dict]
    property_line_note: str
    setback_ok: bool
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    project_id: str
    permit_type: str
    status: str
    jurisdiction: str
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoaApproval(TypedDict):
    id: str
    project_id: str
    status: str
    architectural_packet_ref: str
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    project_id: str
    status: str
    supplier_name: str
    waste_factor_pct: float
    ordered_lines: List[dict]
    dock_id: str
    delivery_window_start: str
    delivery_window_end: str
    created_at: str
    updated_at: str
    version: int


class CrewBooking(TypedDict):
    id: str
    project_id: str
    crew_id: str
    status: str
    window_start: str
    window_end: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    line_item_id: str
    status: str
    new_quantity_units: Optional[float]
    new_accessory: Optional[str]
    expected_project_version: int
    total_delta: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    project_id: str
    milestone: str
    status: str
    pct: float
    amount: float
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    project_id: str
    status: str
    coverage_years: int
    workmanship_only: bool
    created_at: str
    updated_at: str
    version: int
