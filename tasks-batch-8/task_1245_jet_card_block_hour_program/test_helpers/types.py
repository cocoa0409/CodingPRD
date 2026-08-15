"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD resource model exactly. HourBankLedger is an
append-only journal: it carries only ``id`` and ``created_at`` (no
``updated_at``, no ``version``) per PRD section on common resource properties.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPS = "Ops"
    MEMBER = "Member"
    ANONYMOUS = "Anonymous"


class AircraftCategory(str, Enum):
    LIGHT = "LIGHT"
    MIDSIZE = "MIDSIZE"
    SUPER_MID = "SUPER_MID"
    HEAVY = "HEAVY"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MemberTier(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    CORPORATE = "CORPORATE"


class CardStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    REFUNDED = "REFUNDED"


class LedgerEntryKind(str, Enum):
    PURCHASE_GRANT = "PURCHASE_GRANT"
    TRIP_DEBIT = "TRIP_DEBIT"
    EXPIRATION_DEBIT = "EXPIRATION_DEBIT"
    REFUND_DEBIT = "REFUND_DEBIT"
    UPGRADE_DEBIT = "UPGRADE_DEBIT"
    SWAP_ADJUSTMENT = "SWAP_ADJUSTMENT"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE = "MAINTENANCE"
    GROUNDED = "GROUNDED"


class TripKind(str, Enum):
    ONE_WAY = "ONE_WAY"
    ROUND_TRIP = "ROUND_TRIP"


class TripStatus(str, Enum):
    QUOTE = "QUOTE"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    NO_SHOW = "NO_SHOW"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    INSUFFICIENT_HOURS = "INSUFFICIENT_HOURS"
    BLACKOUT = "BLACKOUT"
    AVAILABILITY_WINDOW = "AVAILABILITY_WINDOW"
    PEAK_RESTRICTED = "PEAK_RESTRICTED"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    FLOWN = "FLOWN"
    CANCELED = "CANCELED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RefundStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class UpgradeStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    CANCELED = "CANCELED"


# --- Entity TypedDicts (common_fields: true → id + created_at + updated_at + version) ---


class CardProgram(TypedDict):
    id: str
    program_code: str
    aircraft_category: str
    hours_purchased: int
    purchase_price_cents: int
    swap_ratio_to_lower: float
    swap_ratio_to_higher: float
    expiry_months: int
    taxi_minutes_per_leg: int
    min_billable_minutes_per_leg: int
    peak_surcharge_pct: float
    availability_window_hours: int
    round_trip_discount_pct: float
    early_termination_penalty_pct: float
    fractional_upgrade_ratio: float
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    member_status: str
    tier: str
    home_base_icao: str
    created_at: str
    updated_at: str
    version: int


class JetCard(TypedDict):
    id: str
    member_id: str
    program_id: str
    card_status: str
    purchased_at: Optional[str]
    expires_at: Optional[str]
    hours_total: int
    hours_remaining: float
    hours_consumed: float
    hours_expired: float
    escrow_balance_cents: int
    peak_hours_used: float
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    tail_number: str
    category: str
    home_base_icao: str
    seats: int
    aircraft_status: str
    reposition_rate_cents_per_nm: int
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict):
    id: str
    card_id: str
    trip_kind: str
    departure_icao: str
    arrival_icao: str
    requested_departure_utc: str
    requested_return_utc: Optional[str]
    pax_count: int
    requested_category: str
    swap_applied: bool
    dispatched_aircraft_id: Optional[str]
    trip_status: str
    denial_reason: Optional[str]
    is_peak_period: bool
    quoted_hours: float
    final_hours: Optional[float]
    sla_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class TripLeg(TypedDict):
    id: str
    trip_id: str
    leg_seq: int
    departure_icao: str
    arrival_icao: str
    scheduled_departure_utc: str
    actual_block_minutes: Optional[int]
    billable_minutes: Optional[int]
    billable_hours: Optional[float]
    swap_multiplier: Optional[float]
    debited_hours: Optional[float]
    leg_status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    trip_id: str
    invoice_status: str
    subtotal_cents: int
    peak_surcharge_cents: int
    round_trip_discount_cents: int
    total_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeakCalendar(TypedDict):
    id: str
    program_id: str
    window_start_utc: str
    window_end_utc: str
    label: str
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict):
    id: str
    program_id: str
    window_start_utc: str
    window_end_utc: str
    applies_to_category: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    card_id: str
    principal_cents: int
    available_cents: int
    released_cents: int
    forfeited_cents: int
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    card_id: str
    refund_status: str
    hours_at_request: Optional[float]
    gross_refund_cents: Optional[int]
    penalty_cents: Optional[int]
    net_refund_cents: Optional[int]
    requested_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FractionalUpgrade(TypedDict):
    id: str
    card_id: str
    hours_converted: Optional[float]
    share_fraction: Optional[str]
    upgrade_status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only journal: ONLY id + created_at as common fields.
class HourBankLedgerEntry(TypedDict):
    id: str
    card_id: str
    entry_kind: str
    hours_delta: float
    effective_at: str
    trip_id: Optional[str]
    note: Optional[str]
    created_at: str
