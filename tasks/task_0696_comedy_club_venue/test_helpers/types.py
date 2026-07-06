"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's vocabulary for the Comedy Club & Live-Show Venue platform.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BOOKER = "Booker"
    BOX_OFFICE = "BoxOffice"
    FLOOR_MANAGER = "FloorManager"
    PATRON = "Patron"
    PERFORMER = "Performer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class VenuePosture(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class ShowStatus(str, Enum):
    DRAFT = "DRAFT"
    ON_SALE = "ON_SALE"
    PRIVATE_HELD = "PRIVATE_HELD"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"


class SectionKind(str, Enum):
    GA = "GA"
    RESERVED = "RESERVED"
    TABLE = "TABLE"


class SeatTableStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    DROPPED = "DROPPED"


class LineupRole(str, Enum):
    HOST = "HOST"
    OPENER = "OPENER"
    FEATURE = "FEATURE"
    HEADLINER = "HEADLINER"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    SEATED = "SEATED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EXCHANGED = "EXCHANGED"


class SettlementStatus(str, Enum):
    UNCOLLECTED = "UNCOLLECTED"
    TICKET_PAID = "TICKET_PAID"
    MINIMUM_MET = "MINIMUM_MET"
    REFUNDED = "REFUNDED"


class ScanState(str, Enum):
    ISSUED = "ISSUED"
    SCANNED = "SCANNED"
    VOID = "VOID"


class GuestListStatus(str, Enum):
    LISTED = "LISTED"
    CONVERTED = "CONVERTED"
    REVOKED = "REVOKED"


class PrivateEventStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SettlementState(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# All of these carry the common system fields id/created_at/updated_at/version
# EXCEPT Ticket, which is immutable once issued and carries only id + created_at.

class Venue(TypedDict):
    id: str
    name: str
    settlement_currency: str
    house_fee_pct: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict):
    id: str
    venue_id: str
    title: str
    starts_at: str
    ends_at: str
    doors_buffer_minutes: int
    status: str
    is_private: bool
    ga_sold_count: int
    created_at: str
    updated_at: str
    version: int


class SeatingSection(TypedDict):
    id: str
    show_id: str
    kind: str
    label: str
    ga_capacity: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SeatTable(TypedDict):
    id: str
    section_id: str
    table_number: str
    seats: int
    min_items_per_seat: int
    assigned_server_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Performer(TypedDict):
    id: str
    stage_name: str
    email: str
    standard_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class LineupSlot(TypedDict):
    id: str
    show_id: str
    performer_id: str
    slot_order: int
    role: str
    offered_fee_cents: int
    agreed_fee_cents: Optional[int]
    contract_status: str
    counter_rounds: int
    created_at: str
    updated_at: str
    version: int


class TicketTier(TypedDict):
    id: str
    show_id: str
    section_id: str
    name: str
    price_cents: int
    min_items_override: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    show_id: str
    section_id: str
    tier_id: str
    table_id: Optional[str]
    patron_id: str
    party_size: int
    is_comp: bool
    booking_status: str
    settlement_status: str
    ticket_charge_cents: int
    minimum_due_cents: int
    items_consumed_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


# Ticket: common_fields false — immutable, only id + created_at.
class Ticket(TypedDict):
    id: str
    reservation_id: str
    seat_label: str
    scan_state: str
    created_at: str


class GuestListEntry(TypedDict):
    id: str
    show_id: str
    host_performer_id: str
    guest_name: str
    party_size: int
    minimum_waived: bool
    status: str
    reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Server(TypedDict):
    id: str
    name: str
    max_tables: int
    assigned_table_count: int
    created_at: str
    updated_at: str
    version: int


class PrivateEvent(TypedDict):
    id: str
    show_id: str
    client_name: str
    buyout_fee_cents: int
    deposit_pct: float
    status: str
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    show_id: str
    status: str
    gross_ticket_cents: int
    gross_minimum_cents: int
    buyout_cents: int
    performer_payout_cents: int
    house_cut_cents: int
    net_to_venue_cents: int
    created_at: str
    updated_at: str
    version: int
