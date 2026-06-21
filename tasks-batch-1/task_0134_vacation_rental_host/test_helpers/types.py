"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain carries the common fields id, created_at,
updated_at, and version (the PRD §2.4 common mutation semantics apply to all
resources here), so every TypedDict lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HOST = "Host"
    GUEST = "Guest"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class HostPayoutMethod(str, Enum):
    BANK_TRANSFER = "BANK_TRANSFER"
    PAYPAL = "PAYPAL"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    SNOOZED = "SNOOZED"


class CancellationTier(str, Enum):
    FLEXIBLE = "FLEXIBLE"
    MODERATE = "MODERATE"
    STRICT = "STRICT"


class ChannelName(str, Enum):
    AIRBNB = "AIRBNB"
    VRBO = "VRBO"
    BOOKINGCOM = "BOOKINGCOM"
    DIRECT = "DIRECT"


class ChannelConnectionStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    SYNCING = "SYNCING"
    ERROR = "ERROR"


class CalendarBlockSource(str, Enum):
    BOOKING = "BOOKING"
    MANUAL = "MANUAL"
    IMPORTED = "IMPORTED"


class CalendarBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ScreeningFailureReason(str, Enum):
    NONE = "NONE"
    ID_UNVERIFIED = "ID_UNVERIFIED"
    CHARGEBACK = "CHARGEBACK"
    RISK_THRESHOLD = "RISK_THRESHOLD"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCREENING = "SCREENING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CONFIRMED = "CONFIRMED"
    IN_STAY = "IN_STAY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SecurityDepositStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CLAIM_OPEN = "CLAIM_OPEN"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    DENIED = "DENIED"
    VOID = "VOID"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ImportStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_OVERLAP = "REJECTED_OVERLAP"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Host(TypedDict):
    id: str
    email: str
    display_name: str
    payout_method: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    govt_id_verified: bool
    prior_cancellations: int
    chargeback_flag: bool
    risk_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    host_id: str
    title: str
    base_nightly_rate_cents: int
    cleaning_fee_cents: int
    pet_fee_cents: int
    tax_rate_bps: int
    min_nights: int
    gap_nights: int
    cancellation_tier: str
    security_deposit_cents: int
    platform_commission_bps: int
    payout_delay_days: int
    calendar_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    listing_id: str
    label: str
    window_start: str
    window_end: str
    seasonal_multiplier_bps: int
    weekend_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class ChannelConnection(TypedDict, total=False):
    id: str
    listing_id: str
    channel: str
    status: str
    pending_sync_count: int
    last_synced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CalendarBlock(TypedDict):
    id: str
    listing_id: str
    source: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningResult(TypedDict):
    id: str
    booking_id: str
    guest_id: str
    computed_risk_score: float
    status: str
    failure_reason: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    listing_id: str
    guest_id: str
    calendar_block_id: Optional[str]
    check_in: str
    check_out: str
    nights: int
    pets_count: int
    nightly_subtotal_cents: int
    fees_cents: int
    tax_cents: int
    total_cents: int
    cancellation_tier_snapshot: str
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityDeposit(TypedDict):
    id: str
    booking_id: str
    authorized_cents: int
    held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    security_deposit_id: str
    amount_cents: int
    approved_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    booking_id: str
    host_id: str
    estimated_cents: int
    actual_cents: int
    release_after: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ImportedReservation(TypedDict, total=False):
    id: str
    channel_connection_id: str
    calendar_block_id: Optional[str]
    external_ref: str
    start_date: str
    end_date: str
    import_status: str
    created_at: str
    updated_at: str
    version: int
