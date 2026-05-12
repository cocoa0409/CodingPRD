"""Domain types for the Smart Parking Lot API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties and Versioning) and the entity / state-machine prose in §3.

PRD §2.4 distinguishes two field-shape classes:
- Versioned entities (ParkingLot, Zone, Space, Vehicle, Card, Session,
  Reservation, Violation): expose `id`, `created_at`, `updated_at`,
  `version`.
- Append-only journal-style records (Fine, Payment, RevenueEntry,
  AuditLog): expose only `id` and `created_at`. Tests MUST NOT assert
  `updated_at` or `version` on these.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    DRIVER = "Driver"
    GATE_SYSTEM = "GateSystem"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    PARKING_PARTNER = "ParkingPartner"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Vehicle / Card / Zone enums (PRD §3.1, §3.2, §3.3)
# ---------------------------------------------------------------------------
class VehicleKind(str, Enum):
    REGULAR = "REGULAR"
    EMERGENCY = "EMERGENCY"
    DISABLED = "DISABLED"


class ZoneType(str, Enum):
    STANDARD = "STANDARD"
    VIP = "VIP"
    DISABLED = "DISABLED"
    EMERGENCY = "EMERGENCY"


class CardType(str, Enum):
    MONTHLY = "MONTHLY"
    STORED_VALUE = "STORED_VALUE"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Space parallel state dimensions (PRD §3.1)
# ---------------------------------------------------------------------------
class SpaceOccupancyStatus(str, Enum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"


class SpaceReservationLock(str, Enum):
    UNRESERVED = "UNRESERVED"
    RESERVED = "RESERVED"


# ---------------------------------------------------------------------------
# Session parallel state dimensions (PRD §3.5)
# ---------------------------------------------------------------------------
class SessionOccupancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class SessionPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    DISPUTED = "DISPUTED"


class SessionBillingKind(str, Enum):
    HOURLY = "HOURLY"
    MONTHLY_COVERED = "MONTHLY_COVERED"
    EXEMPT_VEHICLE = "EXEMPT_VEHICLE"


# ---------------------------------------------------------------------------
# Reservation lifecycle (PRD §3.4)
# ---------------------------------------------------------------------------
class ReservationStatus(str, Enum):
    HELD = "HELD"
    MATCHED = "MATCHED"
    EXPIRED_NO_SHOW = "EXPIRED_NO_SHOW"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Violation lifecycle (PRD §3.6)
# ---------------------------------------------------------------------------
class ViolationStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    TOWED_AWAY = "TOWED_AWAY"


class ViolationType(str, Enum):
    OVERSTAY = "OVERSTAY"
    NON_PAYING = "NON_PAYING"
    BLOCKING = "BLOCKING"
    WRONG_ZONE = "WRONG_ZONE"


# ---------------------------------------------------------------------------
# Payment / RevenueEntry kinds (PRD §3.7)
# ---------------------------------------------------------------------------
class PaymentKind(str, Enum):
    SESSION_FEE = "SESSION_FEE"
    FINE_PAYMENT = "FINE_PAYMENT"
    CARD_RECHARGE = "CARD_RECHARGE"
    NO_SHOW_PENALTY = "NO_SHOW_PENALTY"
    REFUND = "REFUND"


class BillingType(str, Enum):
    HOURLY = "HOURLY"
    MONTHLY = "MONTHLY"
    RESERVATION = "RESERVATION"
    NO_SHOW_PENALTY = "NO_SHOW_PENALTY"
    FINE = "FINE"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"


class RevenueSourceKind(str, Enum):
    SESSION = "SESSION"
    RESERVATION = "RESERVATION"
    VIOLATION = "VIOLATION"
    CARD = "CARD"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------------------
# Audit (PRD §2.11)
# ---------------------------------------------------------------------------
class AuditAction(str, Enum):
    BILLING_ADJUSTMENT = "BILLING_ADJUSTMENT"
    RESERVATION_CHANGE = "RESERVATION_CHANGE"
    FINE_WAIVE = "FINE_WAIVE"
    CARD_TRANSFER = "CARD_TRANSFER"


# ---------------------------------------------------------------------------
# External event kinds (PRD §3.8)
# ---------------------------------------------------------------------------
class EventKind(str, Enum):
    LPR_DETECT = "LPR_DETECT"
    PAYMENT_CALLBACK = "PAYMENT_CALLBACK"
    IM_ACK = "IM_ACK"


# ---------------------------------------------------------------------------
# Versioned entity TypedDicts — id + created_at + updated_at + version
# (PRD §2.4)
# ---------------------------------------------------------------------------
class ParkingLot(TypedDict, total=False):
    id: str
    name: str
    timezone: str
    hourly_rate_cents: int
    daily_cap_cents: int
    free_minutes: int
    tow_grace_minutes: int
    reservation_hold_minutes: int
    no_show_penalty_cents: int
    partner_share_bps: int
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    lot_id: str
    code: str
    zone_type: str
    total_spaces: int
    free_spaces: int
    created_at: str
    updated_at: str
    version: int


class Space(TypedDict, total=False):
    id: str
    zone_id: str
    lot_id: str
    label: str
    occupancy_status: str
    reservation_lock: str
    current_session_id: Optional[str]
    last_exited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate: str
    kind: str
    binding_eligible: bool
    open_violation_count: int
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict, total=False):
    id: str
    card_type: str
    status: str
    holder_ref: str
    balance_cents: int
    finalized_balance_cents: int
    monthly_fee_cents: int
    valid_from: str
    valid_until: str
    bound_vehicle_ids: List[str]
    auto_pay_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    lot_id: str
    space_id: str
    vehicle_id: str
    card_id: Optional[str]
    reservation_id: Optional[str]
    occupancy_status: str
    payment_status: str
    entry_at: str
    exit_at: Optional[str]
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    billing_kind: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    lot_id: str
    zone_id: str
    space_id: Optional[str]
    vehicle_id: str
    card_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    matched_session_id: Optional[str]
    penalty_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    lot_id: str
    vehicle_id: str
    session_id: Optional[str]
    space_id: str
    violation_type: str
    photo_uri: Optional[str]
    status: str
    officer_id: str
    detected_at: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only journal entries — id + created_at ONLY (PRD §2.4)
# Tests MUST NOT assert updated_at or version on these.
# ---------------------------------------------------------------------------
class Fine(TypedDict, total=False):
    id: str
    violation_id: str
    amount_cents: int
    components: dict
    paid_at: Optional[str]
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    kind: str
    subject_id: str
    amount_cents: int
    card_id: Optional[str]
    processed_at: str
    external_ref: Optional[str]
    created_at: str


class RevenueEntry(TypedDict, total=False):
    id: str
    lot_id: str
    zone_id: Optional[str]
    billing_type: str
    source_kind: str
    source_id: str
    gross_amount_cents: int
    partner_share_cents: int
    house_share_cents: int
    settlement_period: str
    notes: Optional[str]
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    subject_kind: str
    subject_id: str
    before: dict
    after: dict
    reason: str
    created_at: str
