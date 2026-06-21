"""Domain types for the Photography & Videography Booking API:
entity TypedDicts, status enums, and the role enum.

Field names are PRD-exact (PRD §1, §2, §3). ProofSelection is the one lean
entity (PRD §2.4): it carries only id + created_at, with no updated_at and no
version. Every other entity carries the full id/created_at/updated_at/version set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CLIENT = "Client"
    PHOTOGRAPHER = "Photographer"
    STUDIO_ADMIN = "StudioAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PhotographerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SessionType(str, Enum):
    PORTRAIT = "PORTRAIT"
    WEDDING = "WEDDING"
    EVENT = "EVENT"
    COMMERCIAL = "COMMERCIAL"
    PRODUCT = "PRODUCT"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class BookingWorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHOT = "SHOT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BookingPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUND_PENDING = "REFUND_PENDING"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    SIGNED = "SIGNED"
    VOID = "VOID"


class ShootScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RescheduleReason(str, Enum):
    WEATHER = "WEATHER"
    CLIENT_REQUEST = "CLIENT_REQUEST"
    PHOTOGRAPHER_REQUEST = "PHOTOGRAPHER_REQUEST"


class SecondShooterAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class GalleryStatus(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    PROOFING = "PROOFING"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    FINALIZED = "FINALIZED"


class AddOnLineKind(str, Enum):
    PRINT = "PRINT"
    ALBUM = "ALBUM"


class AddOnOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    CANCELLED = "CANCELLED"


class UsageScope(str, Enum):
    PERSONAL = "PERSONAL"
    COMMERCIAL = "COMMERCIAL"
    EDITORIAL = "EDITORIAL"
    EXCLUSIVE = "EXCLUSIVE"


class Territory(str, Enum):
    LOCAL = "LOCAL"
    NATIONAL = "NATIONAL"
    WORLDWIDE = "WORLDWIDE"


class LicenseGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless noted)
# ---------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Photographer(TypedDict):
    id: str
    email: str
    full_name: str
    skills: List[str]
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionPackage(TypedDict):
    id: str
    name: str
    session_type: str
    tier: str
    base_fee_cents: int
    included_shoot_hours: float
    overage_hourly_rate_cents: int
    included_edited_images: int
    deposit_pct: float
    requires_model_release: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    client_id: str
    package_id: str
    lead_photographer_id: str
    requested_shoot_hours: float
    workflow_status: str
    payment_status: str
    total_fee_cents: int
    deposit_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    booking_id: str
    includes_model_release: bool
    status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShootSchedule(TypedDict):
    id: str
    booking_id: str
    start_utc: str
    end_utc: str
    status: str
    reschedule_reason: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class SecondShooterAssignment(TypedDict):
    id: str
    shoot_schedule_id: str
    photographer_id: str
    billable_hours: float
    assignment_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Gallery(TypedDict):
    id: str
    booking_id: str
    delivered_image_count: int
    status: str
    revision_round: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (PRD §2.4)
class ProofSelection(TypedDict):
    id: str
    gallery_id: str
    selected_image_count: int
    round_index: int
    created_at: str


class AddOnOrder(TypedDict):
    id: str
    booking_id: str
    line_kind: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseGrant(TypedDict):
    id: str
    booking_id: str
    usage_scope: str
    territory: str
    term_months: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
