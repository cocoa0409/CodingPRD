"""Domain types: entity TypedDicts, status enums, role enum for the Catering Event Management API."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CATERING_ADMIN = "CateringAdmin"
    CLIENT = "Client"
    SALES_COORDINATOR = "SalesCoordinator"
    EVENT_CAPTAIN = "EventCaptain"


# --- Status enums ---
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GratuityPolicy(str, Enum):
    INCLUDED = "INCLUDED"
    OPTIONAL = "OPTIONAL"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RoutePosture(str, Enum):
    OPEN = "OPEN"
    ROLLING = "ROLLING"
    CLOSED = "CLOSED"
    BLOCKED = "BLOCKED"


class OrderLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    GUARANTEED = "GUARANTEED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderSettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class AddOnKind(str, Enum):
    DELIVERY = "DELIVERY"
    SETUP = "SETUP"
    STAFFING = "STAFFING"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class StaffingReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class ChangeRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LedgerEntryType(str, Enum):
    DEPOSIT_HOLD = "DEPOSIT_HOLD"
    DEPOSIT_APPLY = "DEPOSIT_APPLY"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"
    CHANGE_FEE_DEBIT = "CHANGE_FEE_DEBIT"


# --- Entity TypedDicts (common_fields: true → id, created_at, updated_at, version) ---
class Client(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    billing_email: str
    tax_exempt: bool
    gratuity_policy: str
    status: str


class EventPackage(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    per_head_cents: int
    min_headcount: int
    lead_time_hours: int
    volume_tiers: List[dict]
    allergen_flags: List[str]
    status: str


class Venue(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    tax_rate_bps: int
    service_fee_bps: int
    max_overlapping_events: int


class ServiceRoute(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    route_date: str
    vehicle_capacity_legs: int
    posture: str
    dispatched_leg_count: int


class Order(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    package_id: str
    venue_id: str
    route_id: Optional[str]
    booked_headcount: int
    guaranteed_headcount: Optional[int]
    event_start: str
    event_end: str
    locked_package_version: Optional[int]
    dietary_counts: Dict[str, int]
    lifecycle_status: str
    settlement_status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    deposit_due_cents: int


class AddOnLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    kind: str
    unit_cents: int
    quantity: int
    per_head_scaled: bool
    staff_ratio: Optional[int]


class DeliveryLeg(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    route_id: str
    preceding_leg_id: Optional[str]
    window_start: str
    window_end: str
    stop_status: str


class StaffingReservation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    reserved_staff: int
    status: str


class ChangeRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    requested_headcount: int
    requested_event_start: str
    counter_headcount: Optional[int]
    change_fee_cents: int
    status: str


# common_fields: false — append-only ledger; carries ONLY id + created_at
class DepositLedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    order_id: str
    entry_type: str
    amount_cents: int
    reason: str
