"""Domain types: entity TypedDicts, status enums, role enum (Valet Parking Operations)."""
from enum import Enum
from typing import TypedDict, Optional


# ── Role enum ─────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ATTENDANT = "Attendant"
    CASHIER = "Cashier"
    SUPERVISOR = "Supervisor"


# ── Status / enum value sets ──────────────────────────────────────────────
class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AttendantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ParkStatus(str, Enum):
    PARKED = "PARKED"
    RETRIEVED = "RETRIEVED"
    CLOSED = "CLOSED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class RetrievalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    STAGING = "STAGING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GrantType(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"
    FULL_COMP = "FULL_COMP"


class GrantStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DamageClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class TipSplitMode(str, Enum):
    EQUAL = "EQUAL"
    WEIGHTED = "WEIGHTED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# ── Entity TypedDicts (all entities carry common fields id/created_at/updated_at/version) ──
class Venue(TypedDict):
    id: str
    name: str
    address: str
    currency: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    venue_id: str
    name: str
    status: str
    window_start: str
    window_end: str
    free_grace_minutes: int
    hourly_rate_cents: int
    daily_max_cents: int
    event_surcharge_cents: int
    overflow_surcharge_cents: int
    tip_split_mode: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    venue_id: str
    name: str
    capacity: int
    occupied_count: int
    overflow_lot_id: Optional[str]
    is_overflow: bool
    overflow_active: bool
    created_at: str
    updated_at: str
    version: int


class LaneAssignment(TypedDict):
    id: str
    venue_id: str
    event_id: str
    lane_code: str
    window_start: str
    window_end: str
    created_at: str
    updated_at: str
    version: int


class Attendant(TypedDict):
    id: str
    venue_id: str
    name: str
    status: str
    total_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    attendant_id: str
    event_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    declared_tips_cents: int
    allocated_tip_cents: int
    liability_holdback_cents: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    event_id: str
    lot_id: str
    attendant_id: str
    license_plate: str
    key_tag: str
    checkin_at: str
    estimated_departure_at: str
    checkout_at: Optional[str]
    park_status: str
    settlement_status: str
    in_overflow: bool
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    net_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RetrievalRequest(TypedDict):
    id: str
    ticket_id: str
    attendant_id: Optional[str]
    status: str
    requested_at: str
    ready_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValidationGrant(TypedDict):
    id: str
    ticket_id: str
    grant_type: str
    value: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    ticket_id: str
    attendant_id: str
    description: str
    claimed_amount_cents: int
    approved_liability_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationReport(TypedDict):
    id: str
    event_id: str
    status: str
    expected_revenue_cents: int
    overflow_surcharge_total_cents: int
    liability_adjustment_cents: int
    declared_cash_cents: Optional[int]
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
