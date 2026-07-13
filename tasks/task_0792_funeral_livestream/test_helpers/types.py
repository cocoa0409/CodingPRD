"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common system-managed fields id, created_at,
updated_at, and version (PRD §2.4), so every TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    FUNERAL_HOME = "FuneralHome"
    OPERATOR = "Operator"
    PLATFORM_ADMIN = "PlatformAdmin"
    GUEST = "Guest"


# --- Status enums ------------------------------------------------------------
class BroadcastStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOID = "VOID"


class StreamStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class RecordingStatus(str, Enum):
    NONE = "NONE"
    RAW = "RAW"
    EDITING = "EDITING"
    READY = "READY"
    DELIVERED = "DELIVERED"


class MemorialStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class OperatorSkill(str, Enum):
    CAMERA = "CAMERA"
    AUDIO = "AUDIO"
    SUPPORT = "SUPPORT"


class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_DUTY = "ON_DUTY"


class AudioSource(str, Enum):
    HOUSE_SYSTEM = "HOUSE_SYSTEM"
    EXTERNAL_MIXER = "EXTERNAL_MIXER"
    SINGLE_MIC = "SINGLE_MIC"


class PrivacyMode(str, Enum):
    PUBLIC = "PUBLIC"
    PASSWORD = "PASSWORD"
    INVITE_ONLY = "INVITE_ONLY"


class VenueBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class CameraAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class GuestbookStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    HIDDEN = "HIDDEN"


class TributeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


# --- Entity TypedDicts -------------------------------------------------------
class FuneralHome(TypedDict):
    id: str
    name: str
    contact_email: str
    stream_credit_balance: int
    donations_pledged_cents: int
    donations_net_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    home_id: str
    name: str
    capacity: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    home_id: str
    full_name: str
    skill: str
    duty_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    home_id: str
    venue_id: str
    decedent_name: str
    scheduled_start: str
    scheduled_end: str
    expected_viewers: int
    priority_support: bool
    camera_count: int
    audio_source: str
    stream_status: str
    broadcast_status: str
    settlement_status: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    estimated_cost_cents: Optional[int]
    final_invoice_cents: Optional[int]
    recording_status: str
    recording_duration_minutes: int
    delivery_email: Optional[str]
    privacy_mode: str
    access_password: Optional[str]
    access_token: str
    failed_access_count: int
    access_locked: bool
    memorial_status: str
    headline: Optional[str]
    donation_goal_cents: int
    donations_net_cents: int
    guestbook_entry_count: int
    created_at: str
    updated_at: str
    version: int


class VenueBooking(TypedDict):
    id: str
    order_id: str
    venue_id: str
    home_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CameraAssignment(TypedDict):
    id: str
    order_id: str
    operator_id: str
    home_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestbookEntry(TypedDict):
    id: str
    order_id: str
    author_name: str
    message: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    order_id: str
    home_id: str
    donor_name: str
    gross_amount_cents: int
    fee_cents: Optional[int]
    net_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TributeVideo(TypedDict):
    id: str
    order_id: str
    title: str
    photo_count: int
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int
