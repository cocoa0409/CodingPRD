"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    PEOPLE_ANALYST = "PeopleAnalyst"
    UNIT_MANAGER = "UnitManager"
    EMPLOYEE_ROLE = "EmployeeRole"
    EXECUTIVE = "Executive"


class Framework(str, Enum):
    EWI = "EWI"
    Q12 = "Q12"
    CUSTOM = "CUSTOM"


class Dimension(str, Enum):
    PURPOSE = "PURPOSE"
    GROWTH = "GROWTH"
    MANAGER_SUPPORT = "MANAGER_SUPPORT"
    BELONGING = "BELONGING"
    WORKLOAD = "WORKLOAD"
    RECOGNITION = "RECOGNITION"


class ItemBankStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SurveyItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class CycleKind(str, Enum):
    CENSUS = "CENSUS"
    PULSE = "PULSE"


class SurveyCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIGURED = "CONFIGURED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCORING = "SCORING"
    REPORTED = "REPORTED"
    ARCHIVED = "ARCHIVED"


class InviteStatus(str, Enum):
    INVITED = "INVITED"
    REMINDED = "REMINDED"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    EXPIRED = "EXPIRED"


class SnapshotScope(str, Enum):
    DIRECT = "DIRECT"
    SUBTREE = "SUBTREE"


class BenchmarkSetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ActionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class ActionItemStatus(str, Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    DROPPED = "DROPPED"


class OutcomeKind(str, Enum):
    ATTRITION = "ATTRITION"
    PERFORMANCE = "PERFORMANCE"


# --- Entity TypedDicts -------------------------------------------------------
# Common-field entities (PRD §2.4) carry id + created_at + updated_at + version.
# SurveyResponse, OutcomeLinkage and ReminderEvent are immutable records that
# carry only id + created_at (updated_at and version are absent on them).


class ItemBank(TypedDict):
    id: str
    name: str
    framework: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyItem(TypedDict):
    id: str
    bank_id: str
    item_code: str
    dimension: str
    weight: float
    has_free_text: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OrgUnit(TypedDict):
    id: str
    name: str
    parent_unit_id: Optional[str]
    manager_user_id: str
    min_n_threshold: int
    verbatim_n_threshold: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    external_ref: str
    unit_id: str
    employment_status: str
    hired_at: str
    exited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyCycle(TypedDict):
    id: str
    label: str
    cycle_kind: str
    bank_id: str
    opens_at: str
    closes_at: str
    status: str
    min_n_default: int
    sampling_ratio: float
    invited_count: int
    submitted_count: int
    partial_count: int
    response_rate: Optional[float]
    attrition_risk: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CycleItem(TypedDict):
    id: str
    cycle_id: str
    item_id: str
    pinned_weight: float
    display_order: int
    created_at: str
    updated_at: str
    version: int


class SurveyInvite(TypedDict):
    id: str
    cycle_id: str
    employee_id: str
    unit_id_at_invite: str
    status: str
    reminder_count: int
    last_reminded_at: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict):
    # Immutable record: id + created_at only (no updated_at, no version).
    id: str
    invite_id: str
    answers: List[Dict[str, Any]]
    is_partial: bool
    created_at: str


class ReportSnapshot(TypedDict):
    id: str
    cycle_id: str
    unit_id: str
    scope: str
    submitted_n: int
    dimension_scores: Dict[str, float]
    overall_score: Optional[float]
    benchmark_percentile: Optional[float]
    numeric_suppressed: bool
    verbatim_suppressed: bool
    generation: int
    created_at: str
    updated_at: str
    version: int


class BenchmarkSet(TypedDict):
    id: str
    name: str
    dimension_scores: List[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ActionPlan(TypedDict):
    id: str
    cycle_id: str
    unit_id: str
    title: str
    focus_dimension: str
    status: str
    submitted_at: Optional[str]
    due_at: str
    progress_pct: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionItem(TypedDict):
    id: str
    plan_id: str
    description: str
    owner_user_id: str
    status: str
    target_at: str
    created_at: str
    updated_at: str
    version: int


class OutcomeLinkage(TypedDict):
    # Immutable record: id + created_at only (no updated_at, no version).
    id: str
    employee_id: str
    cycle_id: str
    outcome_kind: str
    outcome_value: str
    recorded_at: str
    created_at: str


class ReminderEvent(TypedDict):
    # Immutable record: id + created_at only (no updated_at, no version).
    id: str
    invite_id: str
    sent_at: str
    sequence_no: int
    created_at: str
