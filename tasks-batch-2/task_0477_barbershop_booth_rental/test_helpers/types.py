"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system carries the full common-field set
(id, created_at, updated_at, version) per PRD §2.5.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SHOP_OWNER = "ShopOwner"
    RECEPTIONIST = "Receptionist"
    BARBER = "Barber"
    CUSTOMER = "Customer"


# --- Status enums (PRD §3 / state machines) --------------------------------
class ShopStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BarberEmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ChairStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class CompModel(str, Enum):
    BOOTH_RENT = "BOOTH_RENT"
    COMMISSION = "COMMISSION"


class CatalogStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class MembershipStatus(str, Enum):
    OFFERED = "OFFERED"
    RETIRED = "RETIRED"


class CustomerMembershipStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CheckInPunctuality(str, Enum):
    UNSET = "UNSET"
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class QueueTicketStatus(str, Enum):
    WAITING = "WAITING"
    SERVING = "SERVING"
    DONE = "DONE"
    ABANDONED = "ABANDONED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    FINALIZED = "FINALIZED"


# --- Entity TypedDicts (all carry full common-field set per PRD §2.5) -------
class Shop(TypedDict):
    id: str
    name: str
    tax_rate_pct: float
    default_booth_rent_cents: int
    default_commission_pct: float
    product_commission_pct: float
    no_show_fee_cents: int
    no_show_strike_limit: int
    late_grace_minutes: int
    punch_reward_threshold: int
    punch_reward_value_cents: int
    status: str
    gross_service_revenue_cents: int
    gross_product_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Barber(TypedDict):
    id: str
    shop_id: str
    full_name: str
    license_number: str
    license_expires_on: str
    comp_model: str
    booth_rent_cents: int
    commission_pct: float
    license_status: str
    unsettled_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    shop_id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BarberShift(TypedDict):
    id: str
    shop_id: str
    barber_id: str
    chair_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceMenuItem(TypedDict):
    id: str
    shop_id: str
    name: str
    price_cents: int
    duration_minutes: int
    membership_included: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    shop_id: str
    name: str
    price_cents: int
    extra_minutes: int
    membership_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductSku(TypedDict):
    id: str
    shop_id: str
    name: str
    price_cents: int
    stock_qty: int
    commission_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    shop_id: str
    name: str
    monthly_fee_cents: int
    addon_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    shop_id: str
    full_name: str
    email: str
    membership_id: Optional[str]
    membership_status: str
    punch_count: int
    reward_credits: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    barber_id: str
    chair_id: str
    service_item_id: str
    addon_ids: List[str]
    start_utc: str
    end_utc: str
    check_in_punctuality: str
    ticket_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    requested_barber_id: Optional[str]
    queue_position: int
    assigned_barber_id: Optional[str]
    ticket_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    barber_id: str
    appointment_id: Optional[str]
    queue_ticket_id: Optional[str]
    business_date: str
    service_line_ids: List[str]
    addon_line_ids: List[str]
    product_lines: List[dict]
    redeem_reward: bool
    tip_cents: int
    service_net_cents: int
    product_net_cents: int
    tax_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailySettlement(TypedDict):
    id: str
    shop_id: str
    barber_id: str
    business_date: str
    comp_model: str
    service_revenue_cents: int
    product_revenue_cents: int
    tip_total_cents: int
    booth_rent_charged_cents: int
    shop_commission_cents: int
    barber_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
