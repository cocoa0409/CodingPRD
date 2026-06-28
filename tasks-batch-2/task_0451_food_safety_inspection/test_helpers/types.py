"""Domain types: entity TypedDicts, status enums, role enum (Food Safety Inspection API)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PERMIT_CLERK = "PermitClerk"
    INSPECTOR = "Inspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    HEALTH_DIRECTOR = "HealthDirector"


# ─── Status / enum vocabularies ─────────────────────────────────────────────
class FdaCodeClassification(str, Enum):
    CRITICAL = "CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


class EstablishmentStatus(str, Enum):
    PRELICENSE = "PRELICENSE"
    PERMITTED = "PERMITTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RiskCategory(str, Enum):
    CATEGORY_1 = "CATEGORY_1"
    CATEGORY_2 = "CATEGORY_2"
    CATEGORY_3 = "CATEGORY_3"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    CLOSED = "CLOSED"


class PlacardColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class PlanReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    REINSPECTION = "REINSPECTION"
    COMPLAINT = "COMPLAINT"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    AMENDING = "AMENDING"
    FINALIZED = "FINALIZED"


class ViolationResolutionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ClosureReasonCode(str, Enum):
    GRADE_C_AUTOCLOSE = "GRADE_C_AUTOCLOSE"
    CRITICAL_THRESHOLD = "CRITICAL_THRESHOLD"
    IMMINENT_HEALTH_HAZARD = "IMMINENT_HEALTH_HAZARD"


class ClosureOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    VACATED = "VACATED"


class ComplaintType(str, Enum):
    FOODBORNE_ILLNESS = "FOODBORNE_ILLNESS"
    SANITATION = "SANITATION"
    OTHER = "OTHER"


class ComplaintPriority(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class CaseRuling(str, Enum):
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    DISMISSED = "DISMISSED"


class EnforcementCaseStatus(str, Enum):
    OPENED = "OPENED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    CLOSED = "CLOSED"


# ─── Entity TypedDicts (every entity carries id/created_at/updated_at/version) ──
class FdaFoodCode(TypedDict):
    id: str
    code: str
    title: str
    classification: str
    base_demerit_points: int
    repeat_surcharge_points: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    max_daily_route_stops: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Establishment(TypedDict):
    id: str
    name: str
    address: str
    cuisine_type: Optional[str]
    seating_capacity: int
    serves_raw_animal_foods: bool
    does_onsite_processing: bool
    risk_category: str
    routine_interval_days: int
    status: str
    current_score: Optional[int]
    current_grade: Optional[str]
    current_placard_color: Optional[str]
    open_critical_count: int
    next_reinspection_due_index: Optional[int]
    active_closure_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanReview(TypedDict):
    id: str
    establishment_id: str
    submitted_layout_sqft: int
    equipment_count: int
    plan_fee_cents: int
    rejection_reason: Optional[str]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    establishment_id: str
    plan_review_id: str
    issued_index: int
    expires_index: int
    annual_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionRoute(TypedDict):
    id: str
    inspector_id: str
    route_date_index: int
    planned_stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    establishment_id: str
    route_id: Optional[str]
    inspector_id: str
    inspection_type: str
    reinspection_of_id: Optional[str]
    scheduled_index: int
    as_observed_score: Optional[int]
    final_score: Optional[int]
    grade: Optional[str]
    placard_color: Optional[str]
    critical_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    fda_code_id: str
    classification: str
    corrected_on_site: bool
    repeat_offense: bool
    demerit_points_observed: int
    demerit_points_final: int
    resolution_status: str
    created_at: str
    updated_at: str
    version: int


class ClosureOrder(TypedDict):
    id: str
    establishment_id: str
    triggering_inspection_id: str
    reason_code: str
    issued_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    establishment_id: str
    complaint_type: str
    reported_ill_count: int
    severity_score: Optional[int]
    priority: Optional[str]
    linked_inspection_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict):
    id: str
    establishment_id: str
    closure_order_id: Optional[str]
    alleged_penalty_cents: int
    assessed_penalty_cents: Optional[int]
    hearing_index: Optional[int]
    ruling: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
