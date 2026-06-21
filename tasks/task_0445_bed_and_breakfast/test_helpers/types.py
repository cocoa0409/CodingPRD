"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Bed & Breakfast PRD (§2.5, §3.1-§3.9). Entities that carry the
standard system-managed quartet expose id/created_at/updated_at/version; the two
leaner entities (Guest, PaymentLedgerEntry) expose only id and created_at.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Role enum (PRD §2.1) ---------------------------------------------------
class UserRole(str, Enum):
    INNKEEPER = "Innkeeper"
    GUEST = "Guest"
    HOUSEKEEPER = "Housekeeper"
    FINANCE_MANAGER = "FinanceManager"


# --- Status enums -----------------------------------------------------------
class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GiftCertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class BookingChannel(str, Enum):
    DIRECT = "DIRECT"
    OTA = "OTA"


class BreakfastPlanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class HousekeepingTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class TaxRemittanceStatus(str, Enum):
    OPEN = "OPEN"
    FILED = "FILED"


class TaxRemittanceVariant(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"


class LedgerSourceKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    REFUND = "REFUND"
    REDEMPTION = "REDEMPTION"
    FORFEIT = "FORFEIT"


# --- Entity TypedDicts ------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Inn(TypedDict):
    id: str
    name: str
    lodging_tax_rate_bps: int
    checkin_time: str
    checkout_time: str
    gift_cert_expiry_days: int
    turnover_minutes: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    inn_id: str
    name: str
    base_rate_cents: int
    max_occupancy: int
    is_taxable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RatePeriod(TypedDict):
    id: str
    inn_id: str
    label: str
    start_date: str
    end_date: str
    rate_multiplier_bps: int
    min_nights: int
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    inn_id: str
    name: str
    flat_add_cents: int
    per_night_add_cents: int
    is_taxable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftCertificate(TypedDict):
    id: str
    inn_id: str
    code: str
    face_value_cents: int
    remaining_cents: int
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    inn_id: str
    room_id: str
    guest_id: str
    package_id: Optional[str]
    channel: str
    ota_commission_bps: int
    checkin_date: str
    checkout_date: str
    guest_count: int
    nights: int
    room_charge_cents: int
    package_charge_cents: int
    taxable_base_cents: int
    lodging_tax_cents: int
    total_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    refund_cents: int
    net_inn_revenue_cents: int
    reservation_status: str
    payment_status: str
    cancelled_on: Optional[str]
    remitted: bool
    created_at: str
    updated_at: str
    version: int


class BreakfastPlan(TypedDict):
    id: str
    booking_id: str
    party_size: int
    dietary_flags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HousekeepingTask(TypedDict):
    id: str
    booking_id: str
    room_id: str
    ready_after: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxRemittance(TypedDict):
    id: str
    inn_id: str
    period_start: str
    period_end: str
    variant: str
    swept_booking_count: int
    tax_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at ONLY (no updated_at, no version)
class Guest(TypedDict):
    id: str
    inn_id: str
    full_name: str
    email: str
    created_at: str


class PaymentLedgerEntry(TypedDict):
    id: str
    booking_id: str
    source_kind: str
    gift_certificate_id: Optional[str]
    amount_cents: int
    occurred_on: str
    created_at: str
