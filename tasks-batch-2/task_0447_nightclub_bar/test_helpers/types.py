"""Domain types: entity TypedDicts, status enums, role enum (Nightclub & Bar Service)."""
from enum import Enum
from typing import TypedDict, Optional


# ── Status / enum domains ────────────────────────────────────────────────────

class VenuePosture(str, Enum):
    OPEN = "OPEN"
    AT_CAPACITY = "AT_CAPACITY"
    LAST_CALL = "LAST_CALL"
    CLOSED = "CLOSED"


class GuestListStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    REDEEMED = "REDEEMED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    SEATED = "SEATED"
    SETTLED = "SETTLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TabStatus(str, Enum):
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class TabItemCategory(str, Enum):
    ALCOHOL = "ALCOHOL"
    FOOD = "FOOD"
    NA_BEVERAGE = "NA_BEVERAGE"
    SERVICE = "SERVICE"


class EntryStatus(str, Enum):
    INSIDE = "INSIDE"
    EXITED = "EXITED"
    EJECTED = "EJECTED"


class IdCheckOutcome(str, Enum):
    PASS = "PASS"
    REFUSED_UNDERAGE = "REFUSED_UNDERAGE"
    REFUSED_EXPIRED_ID = "REFUSED_EXPIRED_ID"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


class IncidentAction(str, Enum):
    WARNING = "WARNING"
    EJECTION = "EJECTION"
    REFUSAL_SERVICE = "REFUSAL_SERVICE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FLOOR_MANAGER = "FloorManager"
    DOOR_HOST = "DoorHost"
    BARTENDER = "Bartender"
    SECURITY_OFFICER = "SecurityOfficer"


# ── Entity TypedDicts ────────────────────────────────────────────────────────
# Versioned entities (common_fields: true) carry id/created_at/updated_at/version.

class Venue(TypedDict):
    id: str
    name: str
    fire_code_capacity: int
    last_call_offset_minutes: int
    closing_time_utc: str
    cover_base_cents: int
    cover_surge_pct: float
    max_alcohol_strikes: int
    occupancy_count: int
    tabs_open_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Promoter(TypedDict):
    id: str
    venue_id: str
    name: str
    comp_budget_cents: int
    guest_discount_pct: float
    comp_committed_cents: int
    heads_credited: int
    created_at: str
    updated_at: str
    version: int


class GuestListEntry(TypedDict):
    id: str
    venue_id: str
    promoter_id: Optional[str]
    guest_name: str
    party_size: int
    comp_value_cents: int
    status: str
    redeemed_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    venue_id: str
    table_label: str
    party_size: int
    window_start_utc: str
    window_end_utc: str
    spend_minimum_cents: int
    deposit_cents: int
    status: str
    minimum_shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


class Tab(TypedDict):
    id: str
    venue_id: str
    reservation_id: Optional[str]
    patron_name: str
    preauth_cents: int
    gratuity_pct: float
    running_subtotal_cents: int
    final_total_cents: int
    bac_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# TabItem (common_fields: false) — append-only line; ONLY id + created_at,
# NO updated_at, NO version. Its only mutation is the `voided` flag flip.
class TabItem(TypedDict):
    id: str
    tab_id: str
    name: str
    category: str
    qty: int
    unit_price_cents: int
    voided: bool
    created_at: str


class Entry(TypedDict):
    id: str
    venue_id: str
    guest_list_entry_id: Optional[str]
    id_check_id: str
    cover_paid_cents: int
    admitted_at_utc: str
    exited_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IdCheck(TypedDict):
    id: str
    venue_id: str
    patron_name: str
    date_of_birth: str
    id_expiry: str
    computed_age_years: int
    outcome: str
    refusal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityIncident(TypedDict):
    id: str
    venue_id: str
    subject_entry_id: Optional[str]
    severity: str
    action: str
    narrative: str
    logged_at_utc: str
    created_at: str
    updated_at: str
    version: int
