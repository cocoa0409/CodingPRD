"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FITTING_SPECIALIST = "FittingSpecialist"
    REPAIR_TECHNICIAN = "RepairTechnician"
    INSTRUCTOR = "Instructor"
    SHOP_MANAGER = "ShopManager"
    SHOP_ADMIN = "ShopAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StaffRole(str, Enum):
    FITTING_SPECIALIST = "FITTING_SPECIALIST"
    REPAIR_TECHNICIAN = "REPAIR_TECHNICIAN"
    INSTRUCTOR = "INSTRUCTOR"
    SHOP_MANAGER = "SHOP_MANAGER"


class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ComponentType(str, Enum):
    HEAD = "HEAD"
    SHAFT = "SHAFT"
    GRIP = "GRIP"


class BuildSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ORDERED = "ORDERED"
    IN_BUILD = "IN_BUILD"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ComponentOrderStatus(str, Enum):
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    REGRIP = "REGRIP"
    RESHAFT = "RESHAFT"
    LOFT_LIE_ADJUST = "LOFT_LIE_ADJUST"


class TicketWorkStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class TicketPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class AppraisalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class ListingStatus(str, Enum):
    LISTED = "LISTED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class PaymentMethod(str, Enum):
    CREDIT = "CREDIT"
    EXTERNAL = "EXTERNAL"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class OfferBasis(str, Enum):
    GRADE_MATRIX = "GRADE_MATRIX"
    MARKET_COMP = "MARKET_COMP"


class ClubType(str, Enum):
    DRIVER = "DRIVER"
    FAIRWAY = "FAIRWAY"
    HYBRID = "HYBRID"
    IRON_SET = "IRON_SET"
    WEDGE = "WEDGE"
    PUTTER = "PUTTER"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class LedgerReason(str, Enum):
    TRADE_IN_ACCEPT = "TRADE_IN_ACCEPT"
    BUILD_PAYMENT = "BUILD_PAYMENT"
    BUILD_REFUND = "BUILD_REFUND"
    WARRANTY_RESOLUTION = "WARRANTY_RESOLUTION"
    TICKET_PAYMENT = "TICKET_PAYMENT"
    TICKET_REFUND = "TICKET_REFUND"


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    completed_builds_count: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    staff_role: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class LaunchMonitorBay(TypedDict, total=False):
    id: str
    bay_name: str
    status: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class LessonPackage(TypedDict, total=False):
    id: str
    customer_id: str
    total_credits: int
    credits_used: int
    price_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FittingSession(TypedDict, total=False):
    id: str
    customer_id: str
    bay_id: str
    specialist_id: str
    lesson_package_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    credit_consumed: bool
    credit_refunded: bool
    created_at: str
    updated_at: str
    version: int


class ComponentItem(TypedDict, total=False):
    id: str
    sku: str
    component_type: str
    unit_cost_cents: int
    msrp_cents: int
    stock_on_hand: int
    stock_reserved: int
    consumed_total: int
    received_total: int
    created_at: str
    updated_at: str
    version: int


class ClubBuildSpec(TypedDict, total=False):
    id: str
    customer_id: str
    fitting_session_id: str
    head_item_id: str
    shaft_item_id: str
    grip_item_id: str
    length_inches: float
    loft_deg: float
    lie_deg: float
    labor_cents: int
    status: str
    provisional_quote_cents: Optional[int]
    final_price_cents: Optional[int]
    payment_method: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentOrderLine(TypedDict, total=False):
    component_item_id: str
    required_qty: int
    allocated_qty: int


class ComponentOrder(TypedDict, total=False):
    id: str
    build_spec_id: str
    status: str
    lines: List[ComponentOrderLine]
    required_units: int
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict, total=False):
    id: str
    customer_id: str
    club_description: str
    service_type: str
    rush: bool
    shaft_item_id: Optional[str]
    quoted_total_cents: int
    promised_at: str
    deposit_cents: int
    work_status: str
    payment_status: str
    rework_count: int
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict, total=False):
    id: str
    customer_id: str
    clubs: list
    status: str
    offer_basis: Optional[str]
    offered_value_cents: Optional[int]
    offer_expires_at: Optional[str]
    offered_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsedClubListing(TypedDict, total=False):
    id: str
    appraisal_id: str
    appraised_by_staff_id: str
    list_price_cents: int
    status: str
    reserved_by_customer_id: Optional[str]
    reserved_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    customer_id: str
    build_spec_id: Optional[str]
    repair_ticket_id: Optional[str]
    description: str
    coverage_pct: int
    covered_estimate_cents: int
    status: str
    appeal_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (PRD §2.4): carries ONLY id + created_at —
# updated_at and version are absent by design.
class CreditLedgerEntry(TypedDict, total=False):
    id: str
    customer_id: str
    amount_cents: int
    reason: str
    reference_id: str
    created_at: str
