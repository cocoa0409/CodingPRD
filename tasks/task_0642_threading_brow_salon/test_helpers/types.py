"""Domain types: entity TypedDicts, status enums, role enum for the salon API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    SALON_MANAGER = "SalonManager"
    FRONT_DESK_AGENT = "FrontDeskAgent"
    TECHNICIAN = "Technician"
    MEMBER = "Member"


# --- Status enums ----------------------------------------------------------
class SalonStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFF_SHIFT = "OFF_SHIFT"


class ChairStatus(str, Enum):
    OPEN = "OPEN"
    OCCUPIED = "OCCUPIED"
    SANITIZING = "SANITIZING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class ServiceMenuItemStatus(str, Enum):
    LISTED = "LISTED"
    RETIRED = "RETIRED"


class AddOnStatus(str, Enum):
    LISTED = "LISTED"
    RETIRED = "RETIRED"


class PackageTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PackageStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    CANCELLED = "CANCELLED"


class QueueTicketStatus(str, Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    SEATED = "SEATED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class LineType(str, Enum):
    ADDON = "ADDON"
    RETAIL = "RETAIL"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


# --- Entity TypedDicts -----------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Salon(TypedDict):
    id: str
    name: str
    license_number: str
    license_expiry: str
    license_status: str
    loyalty_earn_rate_bps: int
    active_occupancy_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    salon_id: str
    display_name: str
    certified_addon_codes: List[str]
    sanitation_cert_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    salon_id: str
    label: str
    sanitation_minutes: int
    sanitation_ready_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    salon_id: str
    full_name: str
    phone: str
    loyalty_balance: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceMenuItem(TypedDict):
    id: str
    salon_id: str
    code: str
    name: str
    base_price_cents: int
    est_minutes: int
    package_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    salon_id: str
    code: str
    name: str
    price_cents: int
    requires_certification: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailProduct(TypedDict):
    id: str
    salon_id: str
    sku: str
    name: str
    unit_price_cents: int
    stock_qty: int
    initial_stock_qty: int
    created_at: str
    updated_at: str
    version: int


class MembershipPackage(TypedDict):
    id: str
    salon_id: str
    member_id: str
    tier: str
    discount_bps: int
    total_credits: int
    credits_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict):
    id: str
    salon_id: str
    member_id: str
    service_menu_item_id: str
    joined_at: str
    position: int
    called_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    salon_id: str
    queue_ticket_id: str
    member_id: str
    chair_id: str
    technician_id: str
    service_menu_item_id: str
    membership_package_id: Optional[str]
    seated_at: str
    ended_at: Optional[str]
    used_package_credit: bool
    estimate_total_cents: int
    final_total_cents: int
    loyalty_earned: int
    service_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class VisitLineItem(TypedDict):
    id: str
    service_visit_id: str
    line_type: str
    item_ref_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only event, carries ONLY id + created_at
class LoyaltyLedgerEntry(TypedDict):
    id: str
    member_id: str
    service_visit_id: Optional[str]
    entry_type: str
    points: int
    created_at: str
