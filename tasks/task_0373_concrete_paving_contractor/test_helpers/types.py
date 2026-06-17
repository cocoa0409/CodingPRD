"""Domain types: entity TypedDicts, status enums, role enum.

Concrete & Paving Contractor API. Field names mirror the PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ESTIMATOR = "Estimator"
    PROJECT_MANAGER = "ProjectManager"
    FINANCE_OFFICER = "FinanceOfficer"
    INSPECTOR = "Inspector"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATING = "ESTIMATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    POURED = "POURED"
    CURING = "CURING"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"


class MaterialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    POURING = "POURING"
    POURED = "POURED"
    CANCELLED = "CANCELLED"


class CrewAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLAIM_OPEN = "CLAIM_OPEN"
    VOID = "VOID"


class FinishGrade(str, Enum):
    BROOM = "BROOM"
    EXPOSED_AGGREGATE = "EXPOSED_AGGREGATE"
    STAMPED = "STAMPED"


class Reinforcement(str, Enum):
    NONE = "NONE"
    MESH = "MESH"
    REBAR = "REBAR"


class MixType(str, Enum):
    STANDARD = "STANDARD"
    HIGH_EARLY = "HIGH_EARLY"
    FIBER = "FIBER"


class Skill(str, Enum):
    FLATWORK = "FLATWORK"
    FINISHING = "FINISHING"
    PAVING = "PAVING"


class AssetType(str, Enum):
    PUMP_TRUCK = "PUMP_TRUCK"
    POWER_TROWEL = "POWER_TROWEL"
    SCREED = "SCREED"
    MIXER = "MIXER"


class DrawType(str, Enum):
    DEPOSIT = "DEPOSIT"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"


# common_fields: true — id + created_at + updated_at + version
class Project(TypedDict):
    id: str
    site_name: str
    client_name: str
    status: str
    status_before_hold: Optional[str]
    base_contract_amount: float
    provisional_contract_value: float
    committed_contract_value: float
    total_drawn_amount: float
    warranty_risk_score: int
    approved_estimate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlatworkSegment(TypedDict):
    id: str
    project_id: str
    label: str
    area_sqft: float
    thickness_in: float
    finish_grade: str
    reinforcement: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    project_id: str
    provisional_cubic_yards: int
    total_sqft: float
    labor_subtotal: float
    material_subtotal: float
    estimate_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    project_id: str
    jurisdiction: str
    permit_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    project_id: str
    mix_type: str
    order_cubic_yards: int
    pour_scheduled_start: str
    pour_duration_hours: float
    pour_completed_at: Optional[str]
    cure_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, id + created_at only
class WeatherReading(TypedDict):
    id: str
    material_order_id: str
    reading_at: str
    temp_f: float
    precip_pct: float
    created_at: str


class Crew(TypedDict):
    id: str
    crew_name: str
    skill: str
    headcount: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    asset_name: str
    asset_type: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    project_id: str
    crew_id: str
    equipment_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    description: str
    delta_amount: float
    delta_sqft: float
    status: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    project_id: str
    draw_type: str
    amount: float
    status: str
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    project_id: str
    term_months: int
    defect_claims_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
