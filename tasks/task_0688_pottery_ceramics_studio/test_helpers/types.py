"""Domain types: entity TypedDicts, status enums, role enum.

All field names and statuses are taken verbatim from the Pottery Ceramics Studio PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PaintBarItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PaintBarItemCategory(str, Enum):
    GLAZE = "GLAZE"
    UNDERGLAZE = "UNDERGLAZE"
    TOOL = "TOOL"
    TOGO_KIT = "TOGO_KIT"


class StudioVisitStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class VisitType(str, Enum):
    WALK_IN = "WALK_IN"
    PARTY = "PARTY"


class BisquePieceStatus(str, Enum):
    PAINTED = "PAINTED"
    LOADED = "LOADED"
    FIRING = "FIRING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    VOIDED = "VOIDED"


class FiringTemp(str, Enum):
    CONE_06 = "CONE_06"
    CONE_6 = "CONE_6"


class KilnBatchStatus(str, Enum):
    LOADING = "LOADING"
    FIRING = "FIRING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartyBookingStatus(str, Enum):
    DEPOSIT_PENDING = "DEPOSIT_PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    DELUXE = "DELUXE"


class ClassSeriesStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    STARTED = "STARTED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    WITHDRAWN = "WITHDRAWN"
    REFUNDED = "REFUNDED"


class LedgerEntryType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"


class LedgerSourceRefType(str, Enum):
    VISIT = "VISIT"
    ENROLLMENT = "ENROLLMENT"
    BOOKING = "BOOKING"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    STUDIO_STAFF = "StudioStaff"
    STUDIO_MANAGER = "StudioManager"
    LOYALTY_MEMBER = "LoyaltyMember"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Mutable resources carry id + created_at + updated_at + version.

class LoyaltyMember(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    tier: str
    point_balance: int
    lifetime_points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaintBarItem(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    on_hand_qty: int
    reorder_threshold: int
    low_stock: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StudioVisit(TypedDict):
    id: str
    member_id: Optional[str]
    party_size: int
    visit_type: str
    party_booking_id: Optional[str]
    studio_fee_cents: int
    bisque_subtotal_cents: int
    supplies_subtotal_cents: int
    provisional_total_cents: int
    points_redeemed: int
    discount_cents: int
    settled_total_cents: int
    points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BisquePiece(TypedDict):
    id: str
    studio_visit_id: str
    kiln_batch_id: Optional[str]
    sku: str
    name: str
    bisque_price_cents: int
    firing_temp: str
    status: str
    ready_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KilnBatch(TypedDict):
    id: str
    kiln_name: str
    firing_temp: str
    capacity_slots: int
    occupied_slots: int
    turnaround_hours: int
    started_at: Optional[str]
    firing_completes_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyBooking(TypedDict):
    id: str
    member_id: str
    package_tier: str
    guest_count: int
    scheduled_for: str
    package_total_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSeries(TypedDict):
    id: str
    title: str
    session_count: int
    seat_capacity: int
    enrolled_count: int
    price_cents: int
    starts_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    class_series_id: str
    member_id: str
    amount_paid_cents: int
    points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only event record: id + created_at only (no updated_at, no version).
class LoyaltyLedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    points_delta: int
    source_ref_type: str
    source_ref_id: str
    created_at: str
