"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Department, Handler, CategoryRule, WorkOrder, DepartmentAssignment,
  SatisfactionSurvey, SupervisionTask.

- Append-only / immutable-log entities (id + created_at ONLY;
  NO updated_at, NO version):
  ClarificationPause, AuditLog, SyncEvent.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HOTLINE_OPERATOR = "HotlineOperator"
    DISPATCHER = "Dispatcher"
    DEPARTMENT_HANDLER = "DepartmentHandler"
    SUPERVISOR = "Supervisor"
    SURVEY_AGENT = "SurveyAgent"


# ---------------------------------------------------------------------------
# Department / Handler enums (PRD §3.1)
# ---------------------------------------------------------------------------
class DepartmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HandlerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    DISABLED = "DISABLED"


# ---------------------------------------------------------------------------
# WorkOrder enums (PRD §3.2, §3.3, §3.7)
# ---------------------------------------------------------------------------
class Urgency(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkOrderStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CLASSIFIED = "CLASSIFIED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    FOLLOWED_UP = "FOLLOWED_UP"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    REJECTED = "REJECTED"


class ClassificationMode(str, Enum):
    PENDING = "PENDING"
    RULE_BASED = "RULE_BASED"
    AI_ASSISTED = "AI_ASSISTED"


class WarningState(str, Enum):
    NONE = "NONE"
    YELLOW = "YELLOW"
    RED = "RED"
    BREACHED = "BREACHED"


# ---------------------------------------------------------------------------
# DepartmentAssignment enums (PRD §3.4, §3.5, §3.7)
# ---------------------------------------------------------------------------
class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    SUPPORTING = "SUPPORTING"


class AssignmentStageStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REASSIGNED = "REASSIGNED"
    OPINION_SUBMITTED = "OPINION_SUBMITTED"
    ESCALATED = "ESCALATED"


class OpinionDecision(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    ABSTAIN = "ABSTAIN"


class OpinionAggregationDecision(str, Enum):
    PENDING = "PENDING"
    AGREE = "AGREE"
    DISAGREE_OUTVOTED = "DISAGREE_OUTVOTED"
    DISAGREE_BLOCKING = "DISAGREE_BLOCKING"


# ---------------------------------------------------------------------------
# SatisfactionSurvey enums (PRD §3.9)
# ---------------------------------------------------------------------------
class SurveyChannel(str, Enum):
    CALL = "CALL"
    SMS = "SMS"
    IM = "IM"


class SurveyStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# SupervisionTask enums (PRD §3.11)
# ---------------------------------------------------------------------------
class SupervisionReason(str, Enum):
    HIGH_PRIORITY_AUTO = "HIGH_PRIORITY_AUTO"
    INACTIVITY_REMINDER = "INACTIVITY_REMINDER"
    DEADLINE_WARNING = "DEADLINE_WARNING"
    MANUAL = "MANUAL"


class SupervisionStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Audit / Sync (PRD §2.9)
# ---------------------------------------------------------------------------
class AuditAction(str, Enum):
    REGISTER = "REGISTER"
    CLASSIFY = "CLASSIFY"
    DISPATCH = "DISPATCH"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REASSIGN = "REASSIGN"
    OPINION_SUBMIT = "OPINION_SUBMIT"
    ESCALATE = "ESCALATE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    RESOLVE = "RESOLVE"
    SURVEY_DISPATCH = "SURVEY_DISPATCH"
    SURVEY_RESPOND = "SURVEY_RESPOND"
    REOPEN = "REOPEN"
    CLOSE = "CLOSE"
    SUPERVISION_CREATE = "SUPERVISION_CREATE"
    SUPERVISION_ACK = "SUPERVISION_ACK"
    EVENT_SYNC = "EVENT_SYNC"


class SyncEventType(str, Enum):
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"


class TargetPlatform(str, Enum):
    IM = "IM"
    GOVT_AFFAIRS = "GOVT_AFFAIRS"
    INTER_DEPT = "INTER_DEPT"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Versioned entity TypedDicts (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Department(TypedDict, total=False):
    id: str
    name: str
    code: str
    jurisdiction_codes: List[str]
    category_codes: List[str]
    status: str
    pending_work_count: int
    created_at: str
    updated_at: str
    version: int


class Handler(TypedDict, total=False):
    id: str
    full_name: str
    department_id: str
    status: str
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class CategoryRule(TypedDict, total=False):
    id: str
    category_code: str
    sub_category_code: str
    lead_department_code: str
    supporting_department_codes: List[str]
    statutory_time_limit_hours: int
    committed_time_limit_hours: int
    difficulty_base: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    caller_name: Optional[str]
    caller_phone: Optional[str]
    anonymous: bool
    jurisdiction_code: str
    category_code: str
    sub_category_code: str
    content_text: str
    audio_url: Optional[str]
    urgency: str
    difficulty_score: int
    classification_mode: str
    lead_department_id: Optional[str]
    supporting_department_ids: List[str]
    joint_handling: bool
    status: str
    duplicate_of_id: Optional[str]
    statutory_deadline_at: Optional[str]
    committed_deadline_at: Optional[str]
    pause_accumulated_seconds: int
    pause_started_at: Optional[str]
    warning_state: str
    resolution_summary: Optional[str]
    registered_at: str
    closed_at: Optional[str]
    priority_flag: bool
    opinion_aggregation_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepartmentAssignment(TypedDict, total=False):
    id: str
    work_order_id: str
    department_id: str
    role: str
    handler_id: Optional[str]
    stage_status: str
    rejection_reason: Optional[str]
    opinion_text: Optional[str]
    opinion_decision: Optional[str]
    dispatched_at: str
    accepted_at: Optional[str]
    opinion_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict, total=False):
    id: str
    work_order_id: str
    channel: str
    status: str
    score: Optional[int]
    comment: Optional[str]
    dispatched_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionTask(TypedDict, total=False):
    id: str
    work_order_id: str
    reason: str
    status: str
    escalation_level: int
    last_reminder_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity TypedDicts (id + created_at ONLY)
# ---------------------------------------------------------------------------
class ClarificationPause(TypedDict, total=False):
    id: str
    work_order_id: str
    reason: str
    paused_at: str
    resumed_at: Optional[str]
    duration_seconds: Optional[int]
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    work_order_id: Optional[str]
    action: str
    actor_role: str
    actor_id: str
    payload: Dict[str, Any]
    occurred_at: str
    created_at: str


class SyncEvent(TypedDict, total=False):
    id: str
    work_order_id: str
    event_type: str
    target_platform: str
    payload: Dict[str, Any]
    delivery_status: str
    emitted_at: str
    created_at: str


__all__ = [
    "UserRole",
    "DepartmentStatus", "HandlerStatus",
    "Urgency", "WorkOrderStatus", "ClassificationMode", "WarningState",
    "AssignmentRole", "AssignmentStageStatus",
    "OpinionDecision", "OpinionAggregationDecision",
    "SurveyChannel", "SurveyStatus",
    "SupervisionReason", "SupervisionStatus",
    "AuditAction", "SyncEventType", "TargetPlatform", "DeliveryStatus",
    "Department", "Handler", "CategoryRule", "WorkOrder",
    "DepartmentAssignment", "SatisfactionSurvey", "SupervisionTask",
    "ClarificationPause", "AuditLog", "SyncEvent",
]
