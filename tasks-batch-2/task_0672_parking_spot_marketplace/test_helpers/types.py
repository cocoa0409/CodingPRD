"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Parking-Spot Marketplace PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class SpotListingStatus(str, Enum):
    LISTED = "LISTED"
    UNLISTED = "UNLISTED"


class PricingEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class BookingOccupancyStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BookingSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class BookingRateKind(str, Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ViolationKind(str, Enum):
    OVERSTAY = "OVERSTAY"
    UNAUTHORIZED_GATE = "UNAUTHORIZED_GATE"
    NO_SHOW = "NO_SHOW"


class TransferOfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class LedgerEntryType(str, Enum):
    EARNING = "EARNING"
    REVERSAL = "REVERSAL"


class DriverStandingTier(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOST = "Host"
    DRIVER = "Driver"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Versioned resources (common_fields: true) carry id + created_at + updated_at + version.
# AccessPass and PayoutLedgerEntry are append-only: id + created_at only.

class Host(TypedDict):
    id: str
    email: str
    display_name: str
    payout_account_ref: str
    platform_fee_bps: int
    lifetime_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    email: str
    display_name: str
    wallet_balance_cents: int
    violation_points: int
    provisional_violation_points: int
    standing_tier: str
    created_at: str
    updated_at: str
    version: int


class Spot(TypedDict):
    id: str
    host_id: str
    title: str
    zone_code: str
    base_hourly_cents: int
    base_daily_cents: int
    monthly_flat_cents: int
    availability_start: str
    availability_end: str
    overstay_grace_minutes: int
    listing_status: str
    created_at: str
    updated_at: str
    version: int


class PricingEvent(TypedDict):
    id: str
    zone_code: str
    window_start: str
    window_end: str
    surge_multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    spot_id: str
    driver_id: str
    rate_kind: str
    start_at: str
    end_at: str
    quoted_amount_cents: int
    final_amount_cents: Optional[int]
    occupancy_status: str
    settlement_status: str
    actual_checkin_at: Optional[str]
    actual_checkout_at: Optional[str]
    transfer_count: int
    created_at: str
    updated_at: str
    version: int


class ViolationRecord(TypedDict):
    id: str
    booking_id: str
    driver_id: str
    violation_kind: str
    base_points: int
    status: str
    assessed_points: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransferOffer(TypedDict):
    id: str
    booking_id: str
    from_driver_id: str
    to_driver_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (no updated_at, no version).
class AccessPass(TypedDict):
    id: str
    booking_id: str
    qr_token: str
    gate_opens_remaining: int
    created_at: str


class PayoutLedgerEntry(TypedDict):
    id: str
    host_id: str
    booking_id: str
    entry_type: str
    amount_cents: int
    created_at: str
