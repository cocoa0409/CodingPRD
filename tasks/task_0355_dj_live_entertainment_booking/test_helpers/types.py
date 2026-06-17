"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    BOOKING_AGENT = "BookingAgent"
    PERFORMER = "Performer"
    CLIENT = "Client"


class PerformerAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_HOLD = "ON_HOLD"
    BOOKED = "BOOKED"
    INACTIVE = "INACTIVE"


class ActType(str, Enum):
    DJ = "DJ"
    BAND = "BAND"
    SOLO_MUSICIAN = "SOLO_MUSICIAN"
    EMCEE = "EMCEE"
    DUO = "DUO"


class Genre(str, Enum):
    HOUSE = "HOUSE"
    HIP_HOP = "HIP_HOP"
    TOP_40 = "TOP_40"
    JAZZ = "JAZZ"
    ROCK = "ROCK"
    COUNTRY = "COUNTRY"
    LATIN = "LATIN"
    CLASSICAL = "CLASSICAL"
    MULTI_GENRE = "MULTI_GENRE"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EquipmentCategory(str, Enum):
    SOUND = "SOUND"
    LIGHTING = "LIGHTING"
    STAGING = "STAGING"
    FX = "FX"


class BookingStatus(str, Enum):
    INQUIRY = "INQUIRY"
    HOLD = "HOLD"
    CONTRACT_SENT = "CONTRACT_SENT"
    NEGOTIATING = "NEGOTIATING"
    CONFIRMED = "CONFIRMED"
    PERFORMING = "PERFORMING"
    PERFORMED = "PERFORMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    ADJUSTMENT = "ADJUSTMENT"


class CaptureStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOID = "VOID"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    STORE_CREDIT = "STORE_CREDIT"


class ListType(str, Enum):
    REQUEST = "REQUEST"
    DO_NOT_PLAY = "DO_NOT_PLAY"


class SongRequestStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    CONFLICTED = "CONFLICTED"


class ContractStatus(str, Enum):
    ISSUED = "ISSUED"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class BackupStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Performer(TypedDict):
    id: str
    stage_name: str
    act_type: str
    genre: str
    home_zone_id: str
    base_set_rate_cents: int
    overtime_rate_cents_per_15min: int
    availability_status: str
    reliability_score: int
    lifetime_completed_sets: int
    created_at: str
    updated_at: str
    version: int


class TravelZone(TypedDict):
    id: str
    zone_code: str
    name: str
    base_travel_fee_cents: int
    per_mile_fee_cents: int
    surge_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class PackageOffering(TypedDict):
    id: str
    name: str
    tier: str
    flat_package_fee_cents: int
    included_set_minutes: int
    deposit_pct_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    package_id: str
    category: str
    label: str
    unit_fee_cents: int
    requires_power_circuits: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    client_id: str
    performer_id: str
    package_id: str
    event_zone_id: str
    event_start_utc: str
    contracted_set_minutes: int
    event_miles_from_home: int
    actual_set_minutes: Optional[int]
    status: str
    quote_total_cents: int
    final_total_cents: int
    overtime_cents: int
    deposit_required_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    cancellation_fee_cents: int
    active_performer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentRecord(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    capture_status: str
    settlement_status: str
    refund_destination: str
    created_at: str
    updated_at: str
    version: int


class SongRequest(TypedDict):
    id: str
    booking_id: str
    title: str
    artist: Optional[str]
    list_type: str
    priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractDocument(TypedDict):
    id: str
    booking_id: str
    revision: int
    quoted_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackupAssignment(TypedDict):
    id: str
    booking_id: str
    candidate_performer_id: str
    rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, carries ONLY id + created_at (no updated_at, no version)
class BlackoutWindow(TypedDict):
    id: str
    performer_id: str
    start_utc: str
    end_utc: str
    reason: Optional[str]
    created_at: str
