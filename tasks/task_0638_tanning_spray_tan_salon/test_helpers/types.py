"""Domain types: entity TypedDicts, status enums, role enum.

All field names and statuses mirror the Tanning & Spray-Tan Salon PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    SALON_MANAGER = "SalonManager"
    BILLING_SYSTEM = "BillingSystem"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class MemberBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class SprayRoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class SessionStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RetailOrderStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class SessionKind(str, Enum):
    UV = "UV"
    SPRAY = "SPRAY"


class BookingMode(str, Enum):
    RESERVATION = "RESERVATION"
    WALK_IN = "WALK_IN"


class SkinType(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    V = "V"
    VI = "VI"


class EquipmentKind(str, Enum):
    BED = "BED"
    BOOTH = "BOOTH"


class TierCode(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"
    UNLIMITED = "UNLIMITED"


class PaymentKind(str, Enum):
    EFT_DUES = "EFT_DUES"
    RETAIL = "RETAIL"
    UPGRADE = "UPGRADE"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"


class MaintenanceReason(str, Enum):
    SCHEDULED_THRESHOLD = "SCHEDULED_THRESHOLD"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------------------
# Write-once records — carry ONLY id + created_at (PRD §2.4):
#   MembershipPlan, ConsentRecord, Payment, MaintenanceLog
# ---------------------------------------------------------------------------
class MembershipPlan(TypedDict):
    id: str
    created_at: str
    tier_code: str
    monthly_fee_cents: int
    retail_discount_pct: float
    weekly_uv_session_cap: int
    includes_spray: bool


class ConsentRecord(TypedDict):
    id: str
    created_at: str
    member_id: str
    guardian_name: str
    expires_at: str


class Payment(TypedDict):
    id: str
    created_at: str
    member_id: str
    kind: str
    amount_cents: int
    outcome: str
    retail_order_id: Optional[str]


class MaintenanceLog(TypedDict):
    id: str
    created_at: str
    equipment_id: str
    reason: str
    sessions_at_service: int


# ---------------------------------------------------------------------------
# Audit-tracked entities — carry id + created_at + updated_at + version
#   (PRD §2.4): Member, Equipment, SprayRoom, Session, Product, RetailOrder,
#   SalonLedger
# ---------------------------------------------------------------------------
class Member(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    skin_type: str
    plan_id: Optional[str]
    is_minor: bool
    completed_uv_session_count: int
    account_credit_cents: int
    status: str
    billing_status: str
    cycle_anchor_at: Optional[str]
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    name: str
    kind: str
    max_exposure_seconds: int
    turnaround_seconds: int
    status: str
    sessions_since_service: int
    created_at: str
    updated_at: str
    version: int


class SprayRoom(TypedDict):
    id: str
    name: str
    ventilation_buffer_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    member_id: str
    kind: str
    booking_mode: str
    equipment_id: Optional[str]
    spray_room_id: Optional[str]
    start_at: str
    requested_seconds: int
    end_at: str
    allowed_seconds: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    initial_stock: int
    stock_on_hand: int
    units_sold: int
    created_at: str
    updated_at: str
    version: int


class RetailOrderLine(TypedDict):
    product_id: str
    quantity: int


class RetailOrder(TypedDict):
    id: str
    member_id: str
    lines: List[RetailOrderLine]
    subtotal_cents: int
    credit_applied_cents: int
    charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalonLedger(TypedDict):
    id: str
    singleton_key: str
    deferred_revenue_cents: int
    collected_dues_cents: int
    collected_retail_cents: int
    created_at: str
    updated_at: str
    version: int
