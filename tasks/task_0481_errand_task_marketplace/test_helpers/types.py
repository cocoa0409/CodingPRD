"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Errand & Task Marketplace PRD §2.4, §3.1–§3.8.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────

class TaskCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TaskerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class TaskerSkillStatus(str, Enum):
    PENDING = "PENDING"
    VETTED = "VETTED"
    REJECTED = "REJECTED"


class AvailabilityWindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DispatchMode(str, Enum):
    SAME_DAY = "SAME_DAY"
    SCHEDULED = "SCHEDULED"


class PricingModel(str, Enum):
    HOURLY = "HOURLY"
    FIXED = "FIXED"


class CancelledBy(str, Enum):
    CLIENT = "CLIENT"
    TASKER = "TASKER"
    SYSTEM = "SYSTEM"


class FeeTier(str, Enum):
    FREE = "FREE"
    LATE = "LATE"
    LAST_MINUTE = "LAST_MINUTE"


class SenderRole(str, Enum):
    CLIENT = "CLIENT"
    TASKER = "TASKER"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"
    REMOVED = "REMOVED"


class TrustIncidentStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class RecurringSeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class UserRole(str, Enum):
    CLIENT = "Client"
    TASKER = "Tasker"
    DISPATCHER = "Dispatcher"
    TRUST_SAFETY_OFFICER = "TrustSafetyOfficer"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─

class TaskCategory(TypedDict):
    id: str
    name: str
    pricing_model: str
    default_hourly_rate_cents: Optional[int]
    fixed_price_cents: Optional[int]
    default_duration_minutes: int
    requires_vetting: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Tasker(TypedDict):
    id: str
    full_name: str
    hourly_rate_cents: int
    status: str
    trust_score: int
    incident_penalty_total: int
    active_booking_count: int
    completed_booking_count: int
    rating_count: int
    avg_rating: float
    created_at: str
    updated_at: str
    version: int


class TaskerSkill(TypedDict):
    id: str
    tasker_id: str
    category_id: str
    vetting_status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict):
    id: str
    tasker_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class RecurringSeries(TypedDict):
    id: str
    client_id: str
    category_id: str
    tasker_id: str
    frequency: str
    first_start: str
    occurrence_count: int
    estimated_hours: float
    status: str
    generated_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    client_id: str
    category_id: str
    tasker_id: Optional[str]
    series_id: Optional[str]
    dispatch_mode: str
    scheduled_start: str
    scheduled_end: str
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    status: str
    estimated_labor_cents: int
    estimated_service_fee_cents: int
    estimated_total_cents: int
    tip_cents: int
    reschedule_count: int
    proposed_start: Optional[str]
    reschedule_pending: bool
    cancelled_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    booking_id: str
    final_labor_cents: int
    final_service_fee_cents: int
    tip_cents: int
    total_charged_cents: int
    tasker_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Cancellation(TypedDict):
    id: str
    booking_id: str
    cancelled_by: str
    hours_before_start: float
    fee_tier: str
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    booking_id: str
    tasker_id: str
    rating_value: int
    comment: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrustIncident(TypedDict):
    id: str
    tasker_id: str
    booking_id: Optional[str]
    severity: str
    status: str
    penalty_points: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false → id + created_at ONLY) ─────────

class ChatMessage(TypedDict):
    id: str
    booking_id: str
    sender_role: str
    body: str
    created_at: str
