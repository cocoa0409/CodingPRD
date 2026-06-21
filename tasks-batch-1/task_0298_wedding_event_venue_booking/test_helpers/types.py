"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the PRD's Wedding & Event Venue Booking contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─────────────────────────── Role enum ───────────────────────────

class UserRole(str, Enum):
    VENUE_ADMIN = "VenueAdmin"
    COORDINATOR = "Coordinator"
    CLIENT = "Client"
    FINANCE_OFFICER = "FinanceOfficer"


# ─────────────────────────── Status enums ───────────────────────────

class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SpaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CancellationTier(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"
    FLEXIBLE = "FLEXIBLE"


class SpaceKind(str, Enum):
    CEREMONY = "CEREMONY"
    RECEPTION = "RECEPTION"
    DUAL = "DUAL"


class PackageTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BookingStatus(str, Enum):
    INQUIRY = "INQUIRY"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    GUARANTEED = "GUARANTEED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class CancelledReason(str, Enum):
    CLIENT_CANCEL = "CLIENT_CANCEL"
    NONPAYMENT = "NONPAYMENT"


class HoldStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class BlockRole(str, Enum):
    CEREMONY = "CEREMONY"
    RECEPTION = "RECEPTION"


class MilestoneKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class MilestoneStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class PaymentDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"


class PaymentEventStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class VendorRole(str, Enum):
    CATERING = "CATERING"
    FLORAL = "FLORAL"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    MUSIC = "MUSIC"
    RENTAL = "RENTAL"
    OTHER = "OTHER"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class WalkthroughStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReasonKind(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class RequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


# ─────────────────────────── Entity TypedDicts ───────────────────────────
# Entities carrying the full quartet (id, created_at, updated_at, version).

class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    cancellation_tier: str
    force_majeure_fee_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Space(TypedDict):
    id: str
    venue_id: str
    name: str
    space_kind: str
    max_capacity: int
    base_rental_cents: int
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    venue_id: str
    tier: str
    per_head_cents: int
    fb_minimum_cents: int
    service_charge_pct: float
    tax_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Coordinator(TypedDict):
    id: str
    venue_id: str
    full_name: str
    active_booking_cap: int
    assigned_active_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    client_id: str
    venue_id: str
    package_id: str
    coordinator_id: Optional[str]
    event_date: str
    ceremony_start: str
    ceremony_end: str
    reception_start: str
    reception_end: str
    expected_guest_count: int
    booking_status: str
    payment_status: str
    hold_expires_at: Optional[str]
    amount_paid_cents: int
    event_charge_cents: int
    balance_due_cents: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpaceHold(TypedDict):
    id: str
    booking_id: str
    space_id: str
    block_role: str
    occupy_start: str
    occupy_end: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class PaymentMilestone(TypedDict):
    id: str
    booking_id: str
    kind: str
    sequence: int
    amount_due_cents: int
    amount_allocated_cents: int
    due_date: str
    milestone_status: str
    created_at: str
    updated_at: str
    version: int


# Payment is the one lean ledger entity (common_fields: false):
# carries only id + created_at, never updated_at or version.
class Payment(TypedDict):
    id: str
    booking_id: str
    direction: str
    amount_cents: int
    method: str
    status: str
    posted_at: str
    created_at: str


class Vendor(TypedDict):
    id: str
    booking_id: str
    company_name: str
    vendor_role: str
    coi_required: bool
    coi_on_file: bool
    coi_expires_on: Optional[str]
    vendor_status: str
    created_at: str
    updated_at: str
    version: int


class GuestCountGuarantee(TypedDict):
    id: str
    booking_id: str
    guaranteed_count: int
    guarantee_deadline: str
    locked_at: str
    created_at: str
    updated_at: str
    version: int


class Walkthrough(TypedDict):
    id: str
    booking_id: str
    scheduled_start: str
    scheduled_end: str
    walkthrough_status: str
    created_at: str
    updated_at: str
    version: int


class RescheduleRequest(TypedDict):
    id: str
    booking_id: str
    supersedes_request_id: Optional[str]
    reason_kind: str
    proposed_event_date: str
    proposed_ceremony_start: str
    proposed_ceremony_end: str
    proposed_reception_start: str
    proposed_reception_end: str
    request_status: str
    created_at: str
    updated_at: str
    version: int
