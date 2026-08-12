"""Domain types: entity shapes, status enums, role enum (PRD §2.4, §3.1)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    CLIENT = "Client"
    BARISTA = "Barista"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class BaristaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class SkillLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    LEAD = "LEAD"


class CatalogStatus(str, Enum):
    """Shared two-state status for Package, AddOn, TravelZone, InventoryItem,
    and CancellationPolicyTier (PRD §3.1)."""
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PricingModel(str, Enum):
    FLAT = "FLAT"
    PER_CUP = "PER_CUP"


class PricingVariant(str, Enum):
    FLAT_PACKAGE = "FLAT_PACKAGE"
    PER_CUP_METERED = "PER_CUP_METERED"


class TravelVariant(str, Enum):
    BANDED = "BANDED"
    METERED = "METERED"


class BookingStatus(str, Enum):
    QUOTE = "QUOTE"
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    RELEASED = "RELEASED"
    RECONCILED = "RECONCILED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


# ─── Entity shapes (common_fields: id + created_at + updated_at + version) ───

class Client(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoffeeCart(TypedDict, total=False):
    id: str
    cart_code: str
    status: str
    max_drinks_per_hour: int
    requires_power_hookup: bool
    requires_water_hookup: bool
    home_base_lat: float
    home_base_lng: float
    committed_event_count: int
    created_at: str
    updated_at: str
    version: int


class Barista(TypedDict, total=False):
    id: str
    full_name: str
    status: str
    skill_level: str
    latte_art_certified: bool
    hourly_rate_cents: int
    weekly_hour_cap: int
    committed_hours_this_week: int
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict, total=False):
    id: str
    package_code: str
    status: str
    pricing_model: str
    base_hours: int
    included_drinks: int
    flat_price_cents: int
    per_cup_price_cents: int
    per_cup_minimum_cents: int
    max_guests: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict, total=False):
    id: str
    addon_code: str
    status: str
    price_cents: int
    requires_lead_barista: bool
    requires_latte_art_cert: bool
    created_at: str
    updated_at: str
    version: int


class TravelZone(TypedDict, total=False):
    id: str
    zone_code: str
    status: str
    max_distance_km: int
    banded_fee_cents: int
    per_km_rate_cents: int
    min_booking_subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict, total=False):
    id: str
    client_id: str
    package_id: str
    cart_id: str
    travel_zone_id: str
    status: str
    event_start: str
    event_end: str
    guest_count: int
    venue_provides_power: bool
    venue_provides_water: bool
    distance_km: int
    quoted_subtotal_cents: int
    quoted_travel_fee_cents: int
    quoted_total_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    balance_due_cents: int
    balance_paid_cents: int
    refund_paid_cents: int
    pricing_variant_used: Optional[str]
    travel_variant_used: Optional[str]
    cancellation_reason: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# BookingAddOn is immutable once attached: only id + created_at (PRD §2.4).
class BookingAddOn(TypedDict, total=False):
    id: str
    booking_id: str
    addon_id: str
    applied_price_cents: int
    created_at: str


class BaristaAssignment(TypedDict, total=False):
    id: str
    booking_id: str
    barista_id: str
    status: str
    duration_hours: int
    is_primary: bool
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict, total=False):
    id: str
    sku: str
    status: str
    on_hand_units: int
    reserved_units: int
    consumed_units_lifetime: int
    reorder_threshold_units: int
    created_at: str
    updated_at: str
    version: int


class InventoryReservation(TypedDict, total=False):
    id: str
    booking_id: str
    item_id: str
    qty_units: int
    qty_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Payment state moves through explicit settlement actions: only id +
# created_at, no updated_at / version (PRD §2.4).
class Payment(TypedDict, total=False):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    status: str
    idempotency_key: str
    created_at: str


class CancellationPolicyTier(TypedDict, total=False):
    id: str
    tier_code: str
    min_notice_hours: int
    max_notice_hours: int
    deposit_refund_pct: float
    balance_waived: bool
    status: str
    created_at: str
    updated_at: str
    version: int
