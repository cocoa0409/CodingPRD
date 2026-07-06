"""Domain types: entity TypedDicts, status enums, role enum for the Emergency-Alert API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    APPROVER = "Approver"
    CONTACT_ADMIN = "ContactAdmin"
    CONTACT = "Contact"
    INTEGRATOR = "Integrator"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"
    ZH = "ZH"
    VI = "VI"


class Severity(str, Enum):
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ChannelType(str, Enum):
    SMS = "SMS"
    VOICE = "VOICE"
    EMAIL = "EMAIL"
    IPAWS = "IPAWS"


class ContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class OptInStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    OPTED_OUT = "OPTED_OUT"


class GroupStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SubscriptionType(str, Enum):
    GROUP = "GROUP"
    GEO = "GEO"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class AlertStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DISPATCHING = "DISPATCHING"
    SENT = "SENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    EXHAUSTED = "EXHAUSTED"
    SUPPRESSED = "SUPPRESSED"


class ReceiptStatus(str, Enum):
    NONE = "NONE"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class GatewayStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ----

class Contact(TypedDict):
    id: str
    full_name: str
    primary_language: str
    tty_required: bool
    default_lat: Optional[float]
    default_lon: Optional[float]
    quiet_start_min: Optional[int]
    quiet_end_min: Optional[int]
    status: str
    reliability_score: float
    created_at: str
    updated_at: str
    version: int


class ContactChannel(TypedDict):
    id: str
    contact_id: str
    channel_type: str
    address: str
    tty_capable: bool
    opt_in_status: str
    confirmation_token: str
    created_at: str
    updated_at: str
    version: int


class Group(TypedDict):
    id: str
    name: str
    status: str
    member_count: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    contact_id: str
    subscription_type: str
    group_id: Optional[str]
    center_lat: Optional[float]
    center_lon: Optional[float]
    radius_m: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    name: str
    default_severity: str
    body_by_language: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict):
    id: str
    title: str
    severity: str
    channels: List[str]
    template_id: Optional[str]
    target_type: str
    target_group_id: Optional[str]
    center_lat: Optional[float]
    center_lon: Optional[float]
    radius_m: Optional[int]
    effective_from: str
    effective_until: str
    author_user_id: str
    status: str
    revision_count: int
    pending_count: int
    estimated_reach: int
    delivered_reach: int
    sms_billable_segments: int
    source_incident_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlertLocalization(TypedDict):
    id: str
    alert_id: str
    language: str
    message_text: str
    segment_count: int
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    alert_id: str
    contact_id: str
    channel_id: str
    channel_type: str
    language: str
    delivery_status: str
    receipt_status: str
    attempt_count: int
    next_retry_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Gateway(TypedDict):
    id: str
    name: str
    channel_type: str
    capacity_per_window: int
    status: str
    window_count: int
    created_at: str
    updated_at: str
    version: int


class GatewayMaintenanceWindow(TypedDict):
    id: str
    gateway_id: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class Drill(TypedDict):
    id: str
    group_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
