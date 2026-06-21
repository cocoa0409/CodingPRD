"""Domain types: entity TypedDicts, status enums, role enum.

All names use Festival & Fair Management domain terminology from the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum dimensions ─────────────────────────────────────────

class FestivalPosture(str, Enum):
    PLANNING = "PLANNING"
    ON_SALE = "ON_SALE"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    SOLD = "SOLD"
    ACTIVATED = "ACTIVATED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class WristbandLifecycle(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    VOID = "VOID"


class WristbandPresence(str, Enum):
    OUTSIDE = "OUTSIDE"
    INSIDE = "INSIDE"


class VendorApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class AddOnStatus(str, Enum):
    SOLD = "SOLD"
    REFUNDED = "REFUNDED"


class AddOnKind(str, Enum):
    PARKING = "PARKING"
    CAMPING = "CAMPING"


class GateDirection(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class GateOutcome(str, Enum):
    ADMITTED = "ADMITTED"
    EXITED = "EXITED"
    DENIED = "DENIED"


class WalletTxnKind(str, Enum):
    TOPUP = "TOPUP"
    SPEND = "SPEND"
    CASHOUT = "CASHOUT"
    CASHOUT_FEE = "CASHOUT_FEE"


class RefundKind(str, Enum):
    WEATHER_PRORATA = "WEATHER_PRORATA"
    VOLUNTARY_TIERED = "VOLUNTARY_TIERED"


class RefundStatus(str, Enum):
    ISSUED = "ISSUED"


class IncidentType(str, Enum):
    LOST_CHILD = "LOST_CHILD"
    MEDICAL = "MEDICAL"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class TicketType(str, Enum):
    GA = "GA"
    VIP = "VIP"


class BoothTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    FOOD = "FOOD"


class ZoneCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class UserRole(str, Enum):
    FESTIVAL_DIRECTOR = "FestivalDirector"
    BOX_OFFICE = "BoxOffice"
    VENDOR_MANAGER = "VendorManager"
    VENDOR = "Vendor"
    GATE_ATTENDANT = "GateAttendant"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities with full common fields carry id + created_at + updated_at + version.

class Festival(TypedDict):
    id: str
    name: str
    start_date: str
    end_date: str
    total_days: int
    operational_posture: str
    current_festival_day: int
    max_reentries: int
    wristband_cashout_pct: float
    vendor_commission_pct: float
    total_wallet_liability: float
    total_refund_liability: float
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    festival_id: str
    code: str
    slot_capacity: int
    allocated_count: int
    created_at: str
    updated_at: str
    version: int


class Stage(TypedDict):
    id: str
    festival_id: str
    name: str
    changeover_minutes: int
    created_at: str
    updated_at: str
    version: int


class ParkingLot(TypedDict):
    id: str
    festival_id: str
    name: str
    capacity: int
    sold_count: int
    price_per_pass: float
    created_at: str
    updated_at: str
    version: int


class CampingArea(TypedDict):
    id: str
    festival_id: str
    name: str
    capacity: int
    sold_count: int
    price_per_night: float
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    festival_id: str
    wristband_id: Optional[str]
    ticket_type: str
    day_count: int
    face_value: float
    status: str
    purchaser_email: str
    created_at: str
    updated_at: str
    version: int


class Wristband(TypedDict):
    id: str
    festival_id: str
    rfid_uid: str
    lifecycle_status: str
    presence_status: str
    balance: float
    entry_count: int
    reentry_used: int
    created_at: str
    updated_at: str
    version: int


class VendorApplication(TypedDict):
    id: str
    festival_id: str
    vendor_id: str
    booth_zone_id: str
    booth_tier: str
    day_count: int
    power_addon: bool
    status: str
    booth_fee: Optional[float]
    fee_paid: float
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    company_name: str
    contact_email: str
    payout_total: float
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict):
    id: str
    stage_id: str
    festival_id: str
    artist_name: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    festival_id: str
    ticket_id: str
    kind: str
    parking_lot_id: Optional[str]
    camping_area_id: Optional[str]
    nights: Optional[int]
    price: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    festival_id: str
    ticket_id: str
    refund_kind: str
    amount: float
    fee_withheld: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    festival_id: str
    incident_type: str
    linked_wristband_id: Optional[str]
    severity: str
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event logs carry ONLY id + created_at (no updated_at, no version).

class WalletTxn(TypedDict):
    id: str
    wristband_id: str
    festival_id: str
    kind: str
    amount: float
    booth_zone_id: Optional[str]
    vendor_application_id: Optional[str]
    created_at: str


class GateEvent(TypedDict):
    id: str
    festival_id: str
    wristband_id: str
    direction: str
    outcome: str
    deny_reason: Optional[str]
    created_at: str
