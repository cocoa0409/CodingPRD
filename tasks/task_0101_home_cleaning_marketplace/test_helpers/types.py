"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    CLEANER = "Cleaner"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Enumerated states / value sets
# ---------------------------------------------------------------------------
class HomeSize(str, Enum):
    STUDIO = "STUDIO"
    ONE_BR = "ONE_BR"
    TWO_BR = "TWO_BR"
    THREE_BR = "THREE_BR"
    FOUR_PLUS_BR = "FOUR_PLUS_BR"


class CleanerStatus(str, Enum):
    APPLIED = "APPLIED"
    CHECK_PENDING = "CHECK_PENDING"
    CHECK_PASSED = "CHECK_PASSED"
    ACTIVE = "ACTIVE"
    CHECK_FAILED = "CHECK_FAILED"
    SUSPENDED = "SUSPENDED"


class BackgroundCheckResult(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"


class BookingSeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RECLEAN_REQUESTED = "RECLEAN_REQUESTED"
    RECLEAN_SCHEDULED = "RECLEAN_SCHEDULED"


class SuppliesProvidedBy(str, Enum):
    CUSTOMER = "CUSTOMER"
    CLEANER = "CLEANER"


class AddOn(str, Enum):
    DEEP_CLEAN = "DEEP_CLEAN"
    MOVE_OUT = "MOVE_OUT"


class LedgerKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    RECLEAN_CREDIT = "RECLEAN_CREDIT"
    CHANGE_FEE = "CHANGE_FEE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true — carries id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    lifetime_booking_count: int
    created_at: str
    updated_at: str
    version: int


class Address(TypedDict):
    id: str
    customer_id: str
    line1: str
    postal_code: str
    home_size: str
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Cleaner(TypedDict):
    id: str
    email: str
    full_name: str
    service_postal_codes: List[str]
    status: str
    rating_sum: int
    rating_count: int
    completed_job_count: int
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    cleaner_id: str
    provider_ref: str
    result: str
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingPlan(TypedDict):
    id: str
    name: str
    base_price_cents: dict
    deep_clean_surcharge_pct: float
    move_out_surcharge_pct: float
    supplies_fee_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class BookingSeries(TypedDict):
    id: str
    customer_id: str
    address_id: str
    pricing_plan_id: str
    cadence: str
    add_ons: List[str]
    supplies_provided_by: str
    preferred_cleaner_id: Optional[str]
    status: str
    next_occurrence_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    customer_id: str
    address_id: str
    pricing_plan_id: str
    series_id: Optional[str]
    cleaner_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    home_size: str
    add_ons: List[str]
    supplies_provided_by: str
    status: str
    quoted_price_cents: int
    change_fee_cents: int
    is_reclean: bool
    reclean_of_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreferredPro(TypedDict):
    id: str
    customer_id: str
    cleaner_id: str
    priority: int
    created_at: str
    updated_at: str
    version: int


class CleanerPayout(TypedDict):
    id: str
    cleaner_id: str
    booking_id: str
    base_payout_cents: int
    tip_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class Tip(TypedDict):
    id: str
    booking_id: str
    customer_id: str
    cleaner_id: str
    amount_cents: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    customer_id: str
    booking_id: Optional[str]
    kind: str
    amount_cents: int
    created_at: str
