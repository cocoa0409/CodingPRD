"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --- Role enum ---

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HRBP = "HRBP"
    MANAGER = "Manager"
    EMPLOYEE = "Employee"


# --- Status enums ---

class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class UserRoleType(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class ObjectiveLevel(str, Enum):
    COMPANY = "COMPANY"
    DEPARTMENT = "DEPARTMENT"
    TEAM = "TEAM"
    INDIVIDUAL = "INDIVIDUAL"


class ObjectiveStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    IN_REVIEW = "IN_REVIEW"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class MeasurementType(str, Enum):
    NUMERIC = "NUMERIC"
    PERCENTAGE = "PERCENTAGE"
    MILESTONE = "MILESTONE"


class KeyResultStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProgressUpdateType(str, Enum):
    VALUE_CHANGE = "VALUE_CHANGE"
    MILESTONE_TOGGLE = "MILESTONE_TOGGLE"


class DependencyType(str, Enum):
    SUPPORTS = "SUPPORTS"
    BLOCKS = "BLOCKS"
    INFORMS = "INFORMS"


class AlignmentLinkStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BROKEN = "BROKEN"


class CoOwnershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReviewStatus(str, Enum):
    PENDING_SELF = "PENDING_SELF"
    PENDING_MANAGER = "PENDING_MANAGER"
    PENDING_CALIBRATION = "PENDING_CALIBRATION"
    LOCKED = "LOCKED"


class AccessGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SourceSystem(str, Enum):
    HR = "HR"
    PROJECT_MGMT = "PROJECT_MGMT"
    IM = "IM"


class ProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"


class AuditEntityType(str, Enum):
    OBJECTIVE = "OBJECTIVE"
    KEY_RESULT = "KEY_RESULT"
    REVIEW_SCORE = "REVIEW_SCORE"
    ALIGNMENT_LINK = "ALIGNMENT_LINK"
    CO_OWNERSHIP = "CO_OWNERSHIP"
    ACCESS_GRANT = "ACCESS_GRANT"
    OKR_CYCLE = "OKR_CYCLE"


class AuditAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATE_TRANSITION = "STATE_TRANSITION"
    SCORE_CHANGE = "SCORE_CHANGE"
    CALIBRATION = "CALIBRATION"


# --- Entity TypedDicts ---
# common_fields: true → carries id, created_at, updated_at, version

class Department(TypedDict, total=False):
    id: str
    code: str
    name: str
    parent_department_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class User(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    department_id: str
    manager_id: Optional[str]
    role_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OKRCycle(TypedDict, total=False):
    id: str
    cycle_code: str
    year: int
    quarter: int
    start_date: str
    end_date: str
    status: str
    completion_rate: float
    created_at: str
    updated_at: str
    version: int


class Objective(TypedDict, total=False):
    id: str
    cycle_id: str
    parent_objective_id: Optional[str]
    level: str
    department_id: Optional[str]
    owner_user_id: str
    title: str
    description: Optional[str]
    weight: float
    confidential: bool
    status: str
    progress: float
    final_score: Optional[float]
    stale_warning_count: int
    kr_count: int
    child_count: int
    created_at: str
    updated_at: str
    version: int


class KeyResult(TypedDict, total=False):
    id: str
    objective_id: str
    title: str
    measurement_type: str
    start_value: Optional[float]
    target_value: Optional[float]
    current_value: Optional[float]
    milestones: Optional[List[dict]]
    weight: float
    score: float
    status: str
    last_update_at: Optional[str]
    stale: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false → ONLY id + created_at; no updated_at, no version
class ProgressUpdate(TypedDict, total=False):
    id: str
    key_result_id: str
    update_type: str
    new_value: Optional[float]
    milestone_index: Optional[int]
    milestone_completed: Optional[bool]
    comment: Optional[str]
    actor_user_id: str
    score_at_update: float
    created_at: str


class AlignmentLink(TypedDict, total=False):
    id: str
    upstream_objective_id: str
    downstream_objective_id: str
    dependency_type: str
    declared_by_user_id: str
    status: str
    accepted_at: Optional[str]
    rejection_reason: Optional[str]
    forward_impact_score: Optional[float]
    backward_impact_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CoOwnership(TypedDict, total=False):
    id: str
    objective_id: str
    co_owner_user_id: str
    contribution_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewScore(TypedDict, total=False):
    id: str
    objective_id: str
    cycle_id: str
    status: str
    self_score: Optional[float]
    self_submitted_at: Optional[str]
    manager_score: Optional[float]
    manager_submitted_at: Optional[str]
    calibration_score: Optional[float]
    calibration_adjusted_at: Optional[str]
    final_score: Optional[float]
    revision_count: int
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    objective_id: str
    user_id: str
    granted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → only id + created_at
class AuditLog(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_user_id: str
    actor_role: str
    before_value: Optional[Any]
    after_value: Optional[Any]
    api_request_id: str
    created_at: str


# common_fields: false → only id + created_at
class ExternalEvent(TypedDict, total=False):
    id: str
    source_system: str
    external_event_id: str
    event_type: str
    payload: dict
    received_at: str
    processing_status: str
    processed_at: Optional[str]
    side_effect_summary: Optional[str]
    created_at: str
