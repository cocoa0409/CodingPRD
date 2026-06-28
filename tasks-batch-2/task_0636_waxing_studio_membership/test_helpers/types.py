"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    FRONT_DESK = "FrontDesk"
    TECHNICIAN = "Technician"
    MEMBER = "Member"


# --- Status enums ---
class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    UNLIMITED = "UNLIMITED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    CREDIT_HELD = "CREDIT_HELD"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class PaymentMethod(str, Enum):
    CREDIT = "CREDIT"
    DEPOSIT = "DEPOSIT"
    INTRO_FREE = "INTRO_FREE"
    WALK_IN = "WALK_IN"


class RetailSaleStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class CreditEntryType(str, Enum):
    GRANT = "GRANT"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    ROLLOVER_FORFEIT = "ROLLOVER_FORFEIT"
    FREEZE_PARK = "FREEZE_PARK"
    UNFREEZE_RESTORE = "UNFREEZE_RESTORE"


class CreditSourceKind(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    RESERVATION = "RESERVATION"


class StrikeKind(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---
class Location(TypedDict):
    id: str
    name: str
    state_code: str
    open_minute_of_day: int
    close_minute_of_day: int
    deposit_required_cents: int
    no_show_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceType(TypedDict):
    id: str
    name: str
    duration_minutes: int
    buffer_minutes: int
    list_price_cents: int
    credit_cost: int
    intro_eligible: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    unit_price_cents: int
    member_discount_pct: float
    stock_qty: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    location_id: str
    label: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    location_id: str
    full_name: str
    certified_service_ids: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    home_location_id: str
    full_name: str
    email: str
    intro_used: bool
    no_show_strike_count: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    tier: str
    monthly_credit_grant: int
    monthly_fee_cents: int
    max_rollover_credits: int
    status: str
    credit_balance: int
    cycle_anchor_utc: Optional[str]
    cycle_index: int
    freeze_until_utc: Optional[str]
    frozen_cycle_credits: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    location_id: str
    room_id: str
    technician_id: str
    service_type_id: str
    start_utc: str
    end_utc: str
    booking_status: str
    settlement_status: str
    payment_method: str
    membership_id: Optional[str]
    credits_held: int
    deposit_held_cents: int
    charged_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RetailSale(TypedDict):
    id: str
    member_id: str
    reservation_id: str
    product_id: str
    quantity: int
    status: str
    gross_cents: int
    discount_cents: int
    net_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false -> only id + created_at) ---
class CreditLedgerEntry(TypedDict):
    id: str
    membership_id: str
    entry_type: str
    delta_credits: int
    source_kind: str
    source_ref_id: str
    cycle_index: int
    created_at: str


class NoShowStrike(TypedDict):
    id: str
    member_id: str
    reservation_id: str
    strike_kind: str
    fee_charged_cents: int
    status: str
    created_at: str
