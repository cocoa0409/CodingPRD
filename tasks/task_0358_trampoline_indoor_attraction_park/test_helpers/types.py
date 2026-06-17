"""Domain types: entity TypedDicts, status enums, role enum (Trampoline Park API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────
class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class AdmissionStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class Channel(str, Enum):
    RESERVATION = "RESERVATION"
    WALKIN = "WALKIN"


class AddOnSku(str, Enum):
    ARM_SLEEVES = "ARM_SLEEVES"
    LOCKER = "LOCKER"
    FAST_PASS = "FAST_PASS"
    PHOTO_PKG = "PHOTO_PKG"


class MembershipTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    REVIEWED = "REVIEWED"
    SIGNED_OFF = "SIGNED_OFF"
    VOIDED = "VOIDED"


class RenewalOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    PARK_MANAGER = "ParkManager"
    FRONT_DESK = "FrontDesk"
    MEMBER = "Member"
    GUARDIAN = "Guardian"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ───
class Park(TypedDict):
    id: str
    name: str
    timezone: str
    grip_sock_price_cents: int
    minor_age_threshold: int
    walkin_surcharge_cents: int
    party_deposit_pct: float
    cancellation_cutoff_minutes: int
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict):
    id: str
    park_id: str
    starts_at: str
    ends_at: str
    jump_capacity: int
    base_price_cents: int
    seats_taken: int
    status: str
    closed: bool
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    park_id: str
    full_name: str
    birthdate: str
    is_minor: bool
    guardian_participant_id: Optional[str]
    member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    participant_id: str
    signed_by_participant_id: str
    signature_text: str
    signed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JumpPass(TypedDict):
    id: str
    slot_id: str
    participant_id: str
    channel: str
    sock_count: int
    member_id: Optional[str]
    admission_status: str
    payment_status: str
    base_charge_cents: int
    amount_paid_cents: int
    amount_refunded_cents: int
    included_visit_consumed: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at/version)
class PassAddOn(TypedDict):
    id: str
    jump_pass_id: str
    sku: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str


class Member(TypedDict):
    id: str
    park_id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    tier: str
    cycle_anchor_at: str
    status: str
    included_visits_remaining: int
    current_cycle_index: int
    created_at: str
    updated_at: str
    version: int


class PartyRoom(TypedDict):
    id: str
    park_id: str
    name: str
    room_capacity: int
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict):
    id: str
    park_id: str
    name: str
    per_guest_cents: int
    base_room_fee_cents: int
    min_guests: int
    created_at: str
    updated_at: str
    version: int


class PartyBooking(TypedDict):
    id: str
    package_id: str
    room_id: str
    slot_id: str
    host_member_id: Optional[str]
    guest_count: int
    booking_status: str
    total_cents: int
    deposit_cents: int
    balance_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    park_id: str
    jump_pass_id: str
    severity: str
    narrative: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
