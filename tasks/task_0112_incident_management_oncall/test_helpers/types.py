"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Incident Management & On-Call PRD. Append-only event logs
(PageAttempt, WarRoomMessage) carry only id + created_at; all other resources
additionally carry updated_at + version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INCIDENT_COMMANDER = "IncidentCommander"
    RESPONDER_USER = "ResponderUser"


# --- Status enums ---
class ServiceBudgetStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    EXHAUSTED = "EXHAUSTED"


class ServiceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class IncidentSeverity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentLifecycleStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class IncidentEscalationStatus(str, Enum):
    PENDING = "PENDING"
    ESCALATING = "ESCALATING"
    EXHAUSTED = "EXHAUSTED"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class WarRoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PostmortemStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"


class ActionItemStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class PageChannel(str, Enum):
    SMS = "SMS"
    VOICE = "VOICE"
    PUSH = "PUSH"
    EMAIL = "EMAIL"


# --- Entity TypedDicts ---

# common_fields: true — id + created_at + updated_at + version
class Service(TypedDict):
    id: str
    name: str
    tier: str
    error_budget_minutes: int
    budget_status: str
    error_budget_consumed_minutes: int
    error_budget_remaining_minutes: int
    created_at: str
    updated_at: str
    version: int


class Responder(TypedDict):
    id: str
    full_name: str
    email: str
    sms_number: Optional[str]
    voice_number: Optional[str]
    push_token: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OnCallSchedule(TypedDict):
    id: str
    name: str
    service_id: str
    handoff_interval_hours: int
    created_at: str
    updated_at: str
    version: int


class ScheduleShift(TypedDict):
    id: str
    schedule_id: str
    responder_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class EscalationPolicy(TypedDict):
    id: str
    name: str
    service_id: str
    repeat_rounds: int
    created_at: str
    updated_at: str
    version: int


class EscalationTier(TypedDict):
    id: str
    policy_id: str
    schedule_id: str
    tier_level: int
    delay_minutes: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    service_id: str
    status: str
    starts_at: str
    ends_at: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    service_id: str
    policy_id: str
    title: str
    severity: str
    lifecycle_status: str
    escalation_status: str
    current_tier_level: int
    triggered_at: str
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    ack_deadline_at: str
    resolve_deadline_at: str
    ack_sla_breached: bool
    counts_against_budget: bool
    downtime_minutes: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only log: id + created_at only
class PageAttempt(TypedDict):
    id: str
    incident_id: str
    responder_id: str
    tier_level: int
    channel: str
    round_index: int
    created_at: str


class WarRoom(TypedDict):
    id: str
    incident_id: str
    status: str
    bridge_url: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only message log: id + created_at only
class WarRoomMessage(TypedDict):
    id: str
    war_room_id: str
    author_role: str
    author_id: Optional[str]
    body: str
    created_at: str


class Postmortem(TypedDict):
    id: str
    incident_id: str
    status: str
    summary: str
    open_action_item_count: int
    created_at: str
    updated_at: str
    version: int


class ActionItem(TypedDict):
    id: str
    postmortem_id: str
    owner_responder_id: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
