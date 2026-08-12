"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class ServiceLevel(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    SHARED_SUPPORT = "SHARED_SUPPORT"
    TRANSITIONAL = "TRANSITIONAL"


class Qualification(str, Enum):
    NONE = "NONE"
    BEHAVIOR_SUPPORT = "BEHAVIOR_SUPPORT"
    MEDICAL_DELEGATION = "MEDICAL_DELEGATION"
    SIGN_LANGUAGE = "SIGN_LANGUAGE"


class StudentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE_IEP = "ACTIVE_IEP"
    SERVICE_CHANGE_PENDING = "SERVICE_CHANGE_PENDING"
    EXITED = "EXITED"


class ParaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class ChangeType(str, Enum):
    MINUTES_CHANGE = "MINUTES_CHANGE"
    QUALIFICATION_CHANGE = "QUALIFICATION_CHANGE"
    BUILDING_TRANSFER = "BUILDING_TRANSFER"
    EXIT = "EXIT"


class ChangeOrderStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    QUALIFICATION_VERIFIED = "QUALIFICATION_VERIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class FundingStatus(str, Enum):
    PROVISIONALLY_FUNDED = "PROVISIONALLY_FUNDED"
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    SETTLED = "SETTLED"


class EndReason(str, Enum):
    SERVICE_CHANGED = "SERVICE_CHANGED"
    COORDINATOR_ENDED = "COORDINATOR_ENDED"
    PLAN_CLOSED = "PLAN_CLOSED"


class CoveragePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class CoveragePosture(str, Enum):
    OPEN = "OPEN"
    GAPS_OPEN = "GAPS_OPEN"
    FROZEN = "FROZEN"


class AbsenceStatus(str, Enum):
    REPORTED = "REPORTED"
    BACKFILL_PENDING = "BACKFILL_PENDING"
    ESCALATED = "ESCALATED"
    COVERED = "COVERED"
    CANCELLED = "CANCELLED"
    UNCOVERED = "UNCOVERED"


class BackfillStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERSIGNED = "COUNTERSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class UserRole(str, Enum):
    DISTRICT_STAFFING_ADMIN = "DistrictStaffingAdmin"
    SPECIAL_ED_COORDINATOR = "SpecialEdCoordinator"
    BUILDING_ADMINISTRATOR = "BuildingAdministrator"
    TEACHER = "Teacher"
    PARAPROFESSIONAL = "Paraprofessional"
    ANY = "Any"


# All entities carry common fields: id, created_at, updated_at, version (PRD §2.5).

class StaffingPlan(TypedDict):
    id: str
    plan_name: str
    school_year: str
    total_budget_cents: int
    benefit_threshold_minutes: int
    benefit_surcharge_pct: float
    travel_buffer_minutes: int
    committed_cost_cents: int
    settled_cost_cents: int
    cost_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict):
    id: str
    plan_id: str
    name: str
    building_code: str
    hardship_factor: float
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    plan_id: str
    building_id: str
    student_ref: str
    iep_service_level: str
    iep_minutes_per_week: int
    required_qualification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualificationEntry(TypedDict):
    qualification: str
    completed_on: str
    expires_on: Optional[str]
    revoked: bool


class Paraprofessional(TypedDict):
    id: str
    plan_id: str
    home_building_id: str
    full_name: str
    email: str
    base_hourly_wage_cents: int
    contracted_max_weekly_minutes: int
    hire_date: str
    qualifications: List[QualificationEntry]
    weekly_scheduled_minutes: int
    benefit_eligible: bool
    confirmed_benefit_eligible: Optional[bool]
    benefit_variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceChangeOrder(TypedDict):
    id: str
    plan_id: str
    student_id: str
    change_type: str
    new_minutes_per_week: Optional[int]
    new_required_qualification: Optional[str]
    new_building_id: Optional[str]
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    plan_id: str
    student_id: str
    para_id: str
    building_id: str
    start_date: str
    end_date: str
    days_of_week: List[str]
    daily_start_minute: int
    daily_end_minute: int
    service_level_snapshot: str
    required_qualification_snapshot: str
    base_wage_snapshot_cents: int
    daily_cost_cents: int
    projected_weekly_cost_cents: int
    weekly_minutes: int
    end_reason: Optional[str]
    status: str
    funding_status: str
    created_at: str
    updated_at: str
    version: int


class CoveragePlan(TypedDict):
    id: str
    plan_id: str
    building_id: str
    coverage_date: str
    status: str
    coverage_posture: str
    created_at: str
    updated_at: str
    version: int


class AbsenceReport(TypedDict):
    id: str
    plan_id: str
    assignment_id: str
    coverage_plan_id: str
    absence_date: str
    absence_minutes: int
    reason: str
    reported_by_role: str
    declined_para_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackfillAssignment(TypedDict):
    id: str
    absence_id: str
    plan_id: str
    substitute_para_id: str
    coverage_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TimesheetEntry(TypedDict):
    id: str
    plan_id: str
    para_id: str
    assignment_id: str
    work_date: str
    start_minute: int
    end_minute: int
    minutes_worked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict):
    id: str
    plan_id: str
    para_id: str
    period_start: str
    period_end: str
    professionalism_score: int
    instructional_support_score: int
    comments: str
    created_by_user_id: str
    countersigned_by_user_id: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationFormula(TypedDict):
    id: str
    plan_id: str
    version_no: int
    base_grant_cents: int
    per_minute_rate_cents: int
    weight_one_to_one: float
    weight_shared_support: float
    weight_transitional: float
    period_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    plan_id: str
    building_id: str
    formula_id: str
    period_label: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
