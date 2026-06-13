"""Domain types: entity TypedDicts, status enums, role enum for the Salon Spa Booking API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    SALON_OWNER = "SalonOwner"
    FRONT_DESK = "FrontDesk"
    STYLIST = "Stylist"
    CLIENT = "Client"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class StylistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CompensationModel(str, Enum):
    COMMISSION = "COMMISSION"
    BOOTH_RENT = "BOOTH_RENT"


class ResourceType(str, Enum):
    CHAIR = "CHAIR"
    ROOM = "ROOM"


class ResourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class TipSplitPolicy(str, Enum):
    DIRECT = "DIRECT"
    POOLED = "POOLED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class PackagePurchaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CheckoutStatus(str, Enum):
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Salon(TypedDict):
    id: str
    name: str
    timezone: str
    no_show_fee_pct: float
    no_show_suspend_threshold: int
    tip_split_policy: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Stylist(TypedDict):
    id: str
    salon_id: str
    full_name: str
    status: str
    compensation_model: str
    commission_pct: float
    booth_rent_per_appt_cents: int
    buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict):
    id: str
    salon_id: str
    label: str
    resource_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Service(TypedDict):
    id: str
    salon_id: str
    name: str
    duration_minutes: int
    base_price_cents: int
    deposit_pct: float
    requires_room: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    salon_id: str
    full_name: str
    email: str
    status: str
    no_show_strikes: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    salon_id: str
    name: str
    monthly_fee_cents: int
    service_discount_pct: float
    retail_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    client_id: str
    plan_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    salon_id: str
    service_id: str
    session_count: int
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class PackagePurchase(TypedDict):
    id: str
    client_id: str
    package_id: str
    sessions_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    salon_id: str
    client_id: str
    stylist_id: str
    resource_id: str
    service_id: str
    package_purchase_id: Optional[str]
    start_utc: str
    end_utc: str
    status: str
    quoted_service_price_cents: int
    deposit_held_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductSku(TypedDict):
    id: str
    salon_id: str
    sku: str
    name: str
    unit_price_cents: int
    qty_on_hand: int
    created_at: str
    updated_at: str
    version: int


class Checkout(TypedDict):
    id: str
    appointment_id: str
    tip_cents: int
    service_revenue_cents: int
    retail_revenue_cents: int
    stylist_service_earning_cents: int
    salon_service_earning_cents: int
    stylist_tip_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger line, carries ONLY id + created_at
class ProductSale(TypedDict):
    id: str
    checkout_id: str
    product_sku_id: str
    quantity: int
    line_total_cents: int
    created_at: str
