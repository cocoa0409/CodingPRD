"""Domain types: entity TypedDicts, status enums, role enum (PRD §1, §3)."""

from enum import Enum
from typing import Optional, TypedDict


# ─── Role ─────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    MEMBER = "Member"
    CLUB_ADMIN = "ClubAdmin"


# ─── Status / tier enums ──────────────────────────────────────────────────
class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PointsBucketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GuestCertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    USED = "USED"
    REVOKED = "REVOKED"


class WaitlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class StatementPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class StatementAgingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    LISTED = "LISTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ListingType(str, Enum):
    EXCHANGE = "EXCHANGE"
    RENTAL = "RENTAL"


# ─── Entities (all carry common fields: id, created_at, updated_at, version) ─
class Member(TypedDict):
    id: str
    full_name: str
    email: str
    owned_points: int
    tier: str
    account_status: str
    current_use_year: int
    current_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointsBucket(TypedDict):
    id: str
    member_id: str
    use_year: int
    annual_allotment: int
    banked_in: int
    banked_out: int
    borrowed_in: int
    borrowed_out: int
    transferred_in: int
    transferred_out: int
    points_used: int
    points_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Resort(TypedDict):
    id: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class UnitType(TypedDict):
    id: str
    resort_id: str
    name: str
    total_units: int
    points_weekday_low: int
    points_weekend_low: int
    points_weekday_high: int
    points_weekend_high: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    unit_type_id: str
    points_bucket_id: str
    check_in: str
    check_out: str
    nights: int
    points_cost: int
    status: str
    refunded_points: int
    guest_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestCertificate(TypedDict):
    id: str
    reservation_id: str
    guest_name: str
    fee_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Waitlist(TypedDict):
    id: str
    member_id: str
    unit_type_id: str
    points_bucket_id: str
    check_in: str
    check_out: str
    status: str
    promoted_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    member_id: str
    billing_year: int
    issue_date: str
    due_date: str
    maintenance_fee_cents: int
    club_dues_cents: int
    special_assessment_cents: int
    total_due_cents: int
    amount_paid_cents: int
    payment_status: str
    aging_status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    from_member_id: str
    to_member_id: str
    points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    reservation_id: str
    listing_type: str
    ask_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
