"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ----------------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    DISPATCHER = "Dispatcher"
    AGENT = "Agent"
    CITIZEN = "Citizen"
    ANONYMOUS = "Anonymous"


class Priority(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class NotifyChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    NONE = "NONE"


class ServiceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ROUTED = "ROUTED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    DUPLICATE = "DUPLICATE"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class DuplicateClusterStatus(str, Enum):
    OPEN = "OPEN"
    MERGED_CLOSED = "MERGED_CLOSED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class EscalationTier(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    MANUAL = "MANUAL"


class SurveyStatus(str, Enum):
    SENT = "SENT"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class WindowType(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    BLACKOUT = "BLACKOUT"


# ----------------------------------------------------------------------------
# Entity TypedDicts
#   Entities with the full common field set carry id + created_at +
#   updated_at + version. Append-only audit records (StatusNotification,
#   Escalation) carry ONLY id + created_at.
# ----------------------------------------------------------------------------
class ServiceCategory(TypedDict):
    id: str
    name: str
    code: str
    default_priority: str
    default_department_id: str
    requires_geolocation: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    name: str
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    override_department_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    name: str
    open_work_order_count: int
    backlog_threshold: int
    congested: bool
    created_at: str
    updated_at: str
    version: int


class SlaPolicy(TypedDict):
    id: str
    category_id: str
    priority: str
    resolution_sla_hours: int
    escalation_tier1_hours: int
    escalation_tier2_hours: int
    created_at: str
    updated_at: str
    version: int


class Citizen(TypedDict):
    id: str
    email: str
    full_name: str
    notify_channel: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    department_id: str
    full_name: str
    is_supervisor: bool
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    citizen_id: str
    category_id: str
    description: str
    lat: Optional[float]
    lng: Optional[float]
    priority: Optional[str]
    requested_priority: Optional[str]
    jurisdiction_id: Optional[str]
    department_id: Optional[str]
    cluster_id: Optional[str]
    status: str
    sla_deadline_at: Optional[str]
    routed_at: Optional[str]
    resolved_at: Optional[str]
    sla_breached: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class DuplicateCluster(TypedDict):
    id: str
    category_id: str
    canonical_request_id: str
    center_lat: float
    center_lng: float
    member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    request_id: str
    department_id: str
    assigned_agent_id: Optional[str]
    status: str
    completion_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict):
    id: str
    request_id: str
    status: str
    score: Optional[int]
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceWindow(TypedDict):
    id: str
    window_type: str
    department_id: Optional[str]
    jurisdiction_id: Optional[str]
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit records — id + created_at only (no updated_at, no version).
class Escalation(TypedDict):
    id: str
    request_id: str
    tier: str
    reason: str
    status: str
    resolved_by_role: Optional[str]
    created_at: str


class StatusNotification(TypedDict):
    id: str
    request_id: str
    channel: str
    from_status: str
    to_status: str
    message: str
    created_at: str
