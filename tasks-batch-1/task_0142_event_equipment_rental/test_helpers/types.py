"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Event Equipment Rental data model: catalog items, customers,
venues, insurance certificates, rental orders (with two parallel status
dimensions), order lines, delivery runs, crews, and the append-only
deposit ledger / weather event records.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    RENTAL_AGENT = "RentalAgent"
    DEPOSIT_ADJUSTER = "DepositAdjuster"


# ─── Status / category enums ──────────────────────────
class CatalogCategory(str, Enum):
    TENT = "TENT"
    TABLE = "TABLE"
    CHAIR = "CHAIR"
    LINEN = "LINEN"
    BOUNCE_HOUSE = "BOUNCE_HOUSE"


class CatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DeliveryZone(str, Enum):
    LOCAL = "LOCAL"
    EXTENDED = "EXTENDED"
    REMOTE = "REMOTE"


class CoiStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class Fulfillment(str, Enum):
    WILL_CALL = "WILL_CALL"
    DELIVERY = "DELIVERY"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    DEPOSIT_RELEASED = "DEPOSIT_RELEASED"
    DEPOSIT_FORFEITED = "DEPOSIT_FORFEITED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class DeliveryLeg(str, Enum):
    DROP_OFF = "DROP_OFF"
    PICK_UP = "PICK_UP"


class DeliveryRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WeatherSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"


class DepositLedgerKind(str, Enum):
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    FORFEIT = "FORFEIT"


class DepositDisposition(str, Enum):
    RELEASE = "RELEASE"
    FORFEIT = "FORFEIT"


# ─── Entity TypedDicts ────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.
# DepositLedgerEntry and WeatherEvent are append-only: id + created_at only.

class CatalogItem(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    total_units: int
    daily_rate_cents: int
    multi_day_discount_pct: float
    deposit_per_unit_cents: int
    requires_cleaning: bool
    cleaning_fee_cents: int
    requires_coi: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    account_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    customer_id: str
    name: str
    address: str
    delivery_zone: str
    coi_status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    venue_id: str
    carrier_name: str
    coverage_start: str
    coverage_end: str
    coverage_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalOrder(TypedDict):
    id: str
    customer_id: str
    venue_id: Optional[str]
    fulfillment: str
    event_start: str
    event_end: str
    rental_days: int
    booking_status: str
    settlement_status: str
    rental_subtotal_cents: int
    delivery_fee_cents: int
    cleaning_fee_total_cents: int
    deposit_total_cents: int
    grand_total_cents: int
    weather_cancellable: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    item_id: str
    quantity: int
    line_rental_cents: int
    line_deposit_cents: int
    line_cleaning_cents: int
    reserved_window_start: Optional[str]
    reserved_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRun(TypedDict):
    id: str
    order_id: str
    leg: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (no updated_at, no version).
class DepositLedgerEntry(TypedDict):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    reason: str
    created_at: str


class WeatherEvent(TypedDict):
    id: str
    delivery_zone: str
    severity: str
    effective_date: str
    created_at: str
