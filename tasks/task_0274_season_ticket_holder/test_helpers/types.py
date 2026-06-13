"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model. All entities in this domain carry the
common system-managed fields id, created_at, updated_at, version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    ACCOUNT_HOLDER = "AccountHolder"
    FINANCE_CLERK = "FinanceClerk"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SectionTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    VALUE = "VALUE"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD = "SOLD"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PlanType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RELOCATING = "RELOCATING"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SeatAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    REASSIGNED = "REASSIGNED"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOID = "VOID"


class TransferType(str, Enum):
    FORWARD = "FORWARD"
    RESALE = "RESALE"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    FORWARDED = "FORWARDED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class ParkingAddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# --------------------------------------------------------------------------
# Entity TypedDicts — all carry id/created_at/updated_at/version (PRD §2.4)
# --------------------------------------------------------------------------
class Section(TypedDict):
    id: str
    name: str
    tier: str
    base_price_cents: int
    total_seats: int
    available_seats: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    section_id: str
    row_label: str
    seat_number: int
    season_start_date: str
    season_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    full_name: str
    email: str
    consecutive_seasons: int
    priority_points: int
    loyalty_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonPlan(TypedDict):
    id: str
    name: str
    plan_type: str
    game_count: int
    price_multiplier_bps: int
    includes_playoffs: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    season_plan_id: str
    status: str
    locked_price_cents: int
    seat_count: int
    renewal_cycle: int
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict):
    id: str
    subscription_id: str
    seat_id: str
    assigned_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    subscription_id: str
    total_cents: int
    installment_count: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    payment_plan_id: str
    sequence: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketTransfer(TypedDict):
    id: str
    seat_assignment_id: str
    transfer_type: str
    recipient_account_id: str
    listing_price_cents: int
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ParkingZone(TypedDict):
    id: str
    name: str
    capacity: int
    price_cents: int
    active_pass_count: int
    created_at: str
    updated_at: str
    version: int


class ParkingAddOn(TypedDict):
    id: str
    subscription_id: str
    parking_zone_id: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "SectionTier",
    "SeatStatus",
    "LoyaltyTier",
    "AccountStatus",
    "PlanType",
    "SubscriptionStatus",
    "SeatAssignmentStatus",
    "PaymentPlanStatus",
    "InstallmentStatus",
    "TransferType",
    "TransferStatus",
    "ParkingAddOnStatus",
    "Section",
    "Seat",
    "Account",
    "SeasonPlan",
    "Subscription",
    "SeatAssignment",
    "PaymentPlan",
    "Installment",
    "TicketTransfer",
    "ParkingZone",
    "ParkingAddOn",
]
