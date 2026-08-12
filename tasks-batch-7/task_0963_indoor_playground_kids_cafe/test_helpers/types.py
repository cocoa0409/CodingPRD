"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    GUARDIAN = "Guardian"
    FRONT_DESK = "FrontDesk"
    CAFE_STAFF = "CafeStaff"
    MANAGER = "Manager"
    ADMIN = "Admin"


class StaffRole(str, Enum):
    FRONT_DESK = "FRONT_DESK"
    CAFE_STAFF = "CAFE_STAFF"
    MANAGER = "MANAGER"


class MembershipPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MembershipStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class Allergen(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"
    EGG = "EGG"
    WHEAT = "WHEAT"
    SOY = "SOY"
    FISH = "FISH"
    SESAME = "SESAME"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SessionSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(str, Enum):
    MANAGER_CLOSE = "MANAGER_CLOSE"
    EMERGENCY = "EMERGENCY"
    OPS_ENDED = "OPS_ENDED"


class VisitType(str, Enum):
    RESERVATION = "RESERVATION"
    WALK_IN = "WALK_IN"


class AdmissionStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    EVACUATED = "EVACUATED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PREPAID = "PREPAID"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class SockMethod(str, Enum):
    NONE = "NONE"
    OWN_GRIP_SOCKS = "OWN_GRIP_SOCKS"
    PURCHASED = "PURCHASED"
    MEMBERSHIP_PROVIDED = "MEMBERSHIP_PROVIDED"


class PartyRoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class PartyPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PartyBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CafeMenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CafeOrderStatus(str, Enum):
    PLACED = "PLACED"
    PREPARING = "PREPARING"
    SERVED = "SERVED"
    CANCELLED = "CANCELLED"


class LoyaltyKind(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SanitationKind(str, Enum):
    DEEP_CLEAN = "DEEP_CLEAN"
    BALL_PIT_WASH = "BALL_PIT_WASH"
    SURFACE_WIPE = "SURFACE_WIPE"


class SanitationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class IncidentKind(str, Enum):
    LOST_CHILD = "LOST_CHILD"
    INJURY = "INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    BEHAVIOR = "BEHAVIOR"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class MembershipPlan(TypedDict, total=False):
    id: str
    name: str
    monthly_fee_cents: int
    included_session_credits: int
    party_discount_pct: float
    cafe_discount_pct: float
    socks_included: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    membership_plan_id: Optional[str]
    membership_status: str
    credits_granted: int
    credits_consumed: int
    credits_held: int
    credits_available: int
    credits_statement: int
    lifetime_points: int
    points_balance: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict, total=False):
    id: str
    guardian_id: str
    full_name: str
    birth_date: str
    allergies: List[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    id: str
    guardian_id: str
    signed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict, total=False):
    id: str
    slot_date: str
    start_at: str
    end_at: str
    capacity: int
    reservation_quota: int
    reserved_count: int
    checked_in_count: int
    status: str
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    session_slot_id: str
    child_id: str
    guardian_id: str
    visit_type: str
    booked_duration_minutes: Optional[int]
    use_credit: bool
    admission_status: str
    payment_status: str
    sock_method: str
    grip_socks_order_id: Optional[str]
    quoted_cents: Optional[int]
    final_charge_cents: Optional[int]
    refund_delta_cents: Optional[int]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartyRoom(TypedDict, total=False):
    id: str
    name: str
    capacity_children: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict, total=False):
    id: str
    name: str
    duration_minutes: int
    base_price_cents: int
    included_children: int
    extra_child_price_cents: int
    cafe_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyBooking(TypedDict, total=False):
    id: str
    party_room_id: str
    party_package_id: str
    guardian_id: str
    start_at: str
    end_at: str
    child_count: int
    status: str
    quoted_total_cents: int
    deposit_cents: int
    deposit_paid: bool
    proposed_start_at: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class CafeMenuItem(TypedDict, total=False):
    id: str
    name: str
    price_cents: int
    allergen_tags: List[str]
    is_grip_socks: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CafeOrderLine(TypedDict, total=False):
    menu_item_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class CafeOrder(TypedDict, total=False):
    id: str
    guardian_id: str
    visit_id: Optional[str]
    party_booking_id: Optional[str]
    child_ids: List[str]
    lines: List[CafeOrderLine]
    points_to_redeem: int
    subtotal_cents: int
    points_redeemed: int
    total_cents: int
    points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyTransaction(TypedDict, total=False):
    # Append-only ledger entry: carries ONLY id + created_at of the common
    # fields; updated_at and version are absent from it (PRD §2.5).
    id: str
    created_at: str
    guardian_id: str
    kind: str
    points: int
    balance_after: int
    note: str


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SanitationTask(TypedDict, total=False):
    id: str
    party_room_id: str
    kind: str
    due_at: str
    status: str
    checklist_passed: bool
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    visit_id: Optional[str]
    kind: str
    severity: str
    description: str
    status: str
    child_reunited: bool
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    reported_by_staff_id: str
    created_at: str
    updated_at: str
    version: int
