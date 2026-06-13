"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the House Painting Contractor PRD entity model and state machines.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ESTIMATOR = "Estimator"
    PROJECT_MANAGER = "ProjectManager"
    CUSTOMER = "Customer"
    CREW_MEMBER = "CrewMember"


# ─── Status enums ─────────────────────────────────────────────────────────
class ProjectWorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    WALKTHROUGH_PENDING = "WALKTHROUGH_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProjectPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"


class SurfaceStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    REMOVED = "REMOVED"


class ColorSelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderAction(str, Enum):
    ADD_SURFACE = "ADD_SURFACE"
    REMOVE_SURFACE = "REMOVE_SURFACE"
    REVISE_SURFACE = "REVISE_SURFACE"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    FINAL = "FINAL"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class WalkthroughStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class SurfaceKind(str, Enum):
    INTERIOR = "INTERIOR"
    EXTERIOR = "EXTERIOR"
    BOTH = "BOTH"


class FinishType(str, Enum):
    FLAT = "FLAT"
    EGGSHELL = "EGGSHELL"
    SATIN = "SATIN"
    SEMI_GLOSS = "SEMI_GLOSS"
    GLOSS = "GLOSS"


class SkillLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class EquipmentKind(str, Enum):
    SPRAYER = "SPRAYER"
    SCAFFOLD = "SCAFFOLD"
    LIFT = "LIFT"


class PrepLevel(str, Enum):
    LIGHT = "LIGHT"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    RESTORATION = "RESTORATION"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities carrying the full common-field quartet (id + created_at + updated_at + version).

class PaintProduct(TypedDict):
    id: str
    name: str
    surface_kind: str
    finish_type: str
    price_per_gallon_cents: int
    coverage_sqft_per_gallon_per_coat: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    skill_level: str
    daily_rate_cents: int
    scheduled_day_count: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    name: str
    equipment_kind: str
    total_units: int
    units_reserved: int
    created_at: str
    updated_at: str
    version: int


class WeatherWindow(TypedDict):
    id: str
    window_date: str
    forecast_temp_f: int
    precipitation_pct: int
    exterior_suitable: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    site_address: str
    scope: str
    deposit_pct: int
    workflow_status: str
    payment_status: str
    estimate_material_cents: int
    estimate_labor_cents: int
    estimate_total_cents: int
    revised_total_cents: int
    final_total_cents: Optional[int]
    deposit_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    warranty_months: int
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Surface(TypedDict):
    id: str
    project_id: str
    label: str
    surface_kind: str
    area_sqft: int
    coats: int
    prep_level: str
    paint_product_id: str
    status: str
    color_locked: bool
    created_at: str
    updated_at: str
    version: int


class ColorSelection(TypedDict):
    id: str
    project_id: str
    surface_id: str
    color_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    project_id: str
    surface_id: str
    gallons_required: int
    material_cost_cents: int
    labor_hours: float
    labor_cost_cents: int
    executed: bool
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    reason: str
    action: str
    target_surface_id: Optional[str]
    new_label: Optional[str]
    new_surface_kind: Optional[str]
    new_area_sqft: Optional[int]
    new_coats: Optional[int]
    new_prep_level: Optional[str]
    new_paint_product_id: Optional[str]
    status: str
    delta_total_cents: int
    applied_project_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    project_id: str
    crew_member_id: str
    equipment_id: Optional[str]
    start_date: str
    end_date: str
    requires_exterior_weather: bool
    status: str
    day_count: int
    created_at: str
    updated_at: str
    version: int


class Walkthrough(TypedDict):
    id: str
    project_id: str
    punch_list_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    surface_id: str
    description: str
    filed_at: str
    status: str
    provisional_payout_cents: int
    final_payout_cents: Optional[int]
    logged_touchup_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Payment is an append-only ledger row: id + created_at only.
# It carries NO updated_at and NO version (PRD §2.4).
class Payment(TypedDict):
    id: str
    project_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
