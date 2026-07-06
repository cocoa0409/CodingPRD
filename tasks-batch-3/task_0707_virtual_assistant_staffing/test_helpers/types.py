"""Domain types: entity TypedDicts, status enums, and the role enum.

All names and fields follow the Va-Staffing PRD verbatim. Entities that the PRD
declares immutable reference records (SkillTag, SlaPolicy, Clock) carry only
``id`` and ``created_at`` — they have no ``updated_at`` and no ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────
class ClientStatus(str, Enum):
    PENDING = "PENDING"
    SCOPED = "SCOPED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VirtualAssistantStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ENGAGED = "ENGAGED"
    BENCHED = "BENCHED"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    REJECTED = "REJECTED"


class RetainerCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskPriority(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class SlaState(str, Enum):
    ON_TRACK = "ON_TRACK"
    RESPONSE_BREACHED = "RESPONSE_BREACHED"
    RESOLUTION_BREACHED = "RESOLUTION_BREACHED"


class TimeEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AddOnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REPLACED = "REPLACED"


class EscalationReason(str, Enum):
    SLA_BREACH = "SLA_BREACH"
    QUALITY = "QUALITY"
    AVAILABILITY = "AVAILABILITY"
    OTHER = "OTHER"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


class SlaTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class UserRole(str, Enum):
    STAFFING_MANAGER = "StaffingManager"
    CLIENT = "Client"
    VA = "VA"


# ─── Immutable reference records: only id + created_at ─────────────────────
class SkillTag(TypedDict):
    id: str
    created_at: str
    code: str
    name: str
    is_specialized: bool


class SlaPolicy(TypedDict):
    id: str
    created_at: str
    tier: str
    response_minutes: int
    resolution_hours: int
    breach_penalty_pct: float


class Clock(TypedDict):
    id: str
    created_at: str
    current_utc: str


# ─── Full-lifecycle entities: id + created_at + updated_at + version ───────
class Client(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    contact_email: str
    status: str
    scope_summary: Optional[str]
    required_skill_tag_ids: List[str]
    monthly_retainer_hours: float
    base_rate_cents: int
    overage_rate_cents: int
    rollover_cap_hours: float
    active_engagement_id: Optional[str]
    open_task_count: int


class VirtualAssistant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    status: str
    skill_tag_ids: List[str]
    weekly_capacity_hours: float
    rating: float
    active_engagement_count: int


class Engagement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    va_id: str
    status: str
    match_score: float
    superseded_by_engagement_id: Optional[str]
    onboarding_checklist_done: bool


class RetainerCycle(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    sequence_no: int
    status: str
    granted_hours: float
    rolled_in_hours: float
    consumed_hours: float
    available_hours: float
    overage_hours: float
    opened_at_iso: str
    closed_at_iso: Optional[str]


class Task(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    engagement_id: Optional[str]
    title: str
    priority: str
    required_skill_tag_id: Optional[str]
    status: str
    estimated_hours: float
    assigned_at_iso: Optional[str]
    first_action_at_iso: Optional[str]
    completed_at_iso: Optional[str]
    response_due_iso: Optional[str]
    resolution_due_iso: Optional[str]
    sla_state: str
    billed_hours: float
    blocked_reason: Optional[str]


class TimeEntry(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    task_id: str
    cycle_id: str
    va_id: str
    status: str
    raw_minutes: int
    billable_hours: float
    note: Optional[str]
    approved_at_iso: Optional[str]


class AddOn(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    skill_tag_id: str
    status: str
    surcharge_rate_cents: int


class Escalation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    client_id: str
    reason: str
    status: str
    replacement_engagement_id: Optional[str]


class Invoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    cycle_id: str
    variant: str
    status: str
    base_charge_cents: int
    overage_charge_cents: int
    surcharge_cents: int
    sla_credit_cents: int
    total_cents: int
    utilization_pct: float
