"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Mobile Bartending & Catering PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT = "Client"
    COORDINATOR = "Coordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BARTENDER = "Bartender"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class PackageTier(str, Enum):
    BEER_WINE = "BEER_WINE"
    CLASSIC = "CLASSIC"
    PREMIUM = "PREMIUM"
    LUXURY = "LUXURY"


class BartenderAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    ENGAGED = "ENGAGED"
    INACTIVE = "INACTIVE"


class BarKitStationType(str, Enum):
    BEER_WINE = "BEER_WINE"
    FULL_BAR = "FULL_BAR"
    MOBILE_CART = "MOBILE_CART"


class BarKitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class VenueType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"
    MIXED = "MIXED"


class EventBookingStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EventPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"
    SETTLED = "SETTLED"


class CompliancePosture(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ABCModel(str, Enum):
    HOST_NO_SALE = "HOST_NO_SALE"
    CASH_BAR = "CASH_BAR"
    NONE = "NONE"


class ComplianceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    BACK = "BACK"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class KitReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class InventoryPlanStatus(str, Enum):
    GENERATED = "GENERATED"
    STALE = "STALE"


class DrinkType(str, Enum):
    BEER = "BEER"
    WINE = "WINE"
    COCKTAIL = "COCKTAIL"
    MOCKTAIL = "MOCKTAIL"


class SpiritBase(str, Enum):
    VODKA = "VODKA"
    GIN = "GIN"
    WHISKEY = "WHISKEY"
    RUM = "RUM"
    TEQUILA = "TEQUILA"
    NONE = "NONE"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    BREAKAGE_CHARGE = "BREAKAGE_CHARGE"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CASH = "CASH"
    SYSTEM = "SYSTEM"


class BreakageStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"


class CancelledBy(str, Enum):
    CLIENT = "CLIENT"
    COORDINATOR = "COORDINATOR"
    SYSTEM = "SYSTEM"
    BARTENDER = "BARTENDER"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#   common_fields: true  -> id, created_at, updated_at, version
#   common_fields: false -> id, created_at ONLY  (Payment ledger record)
# ---------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    home_state_code: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    tier: str
    name: str
    base_price_cents: int
    included_guest_count: int
    per_guest_overage_cents: int
    included_hours: int
    min_hours: int
    per_hour_overage_cents: int
    drinks_per_guest_per_hour: float
    guests_per_bartender: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Bartender(TypedDict):
    id: str
    full_name: str
    email: str
    certification_expiry: str
    hourly_rate_cents: int
    home_state_code: str
    availability_status: str
    upcoming_assignment_count: int
    reliability_score_strict: int
    reliability_score_lenient: int
    created_at: str
    updated_at: str
    version: int


class BarKit(TypedDict):
    id: str
    kit_name: str
    station_type: str
    glassware_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    client_id: str
    package_id: str
    title: str
    venue_state_code: str
    venue_type: str
    event_start: str
    event_end: str
    guest_count: int
    byob_host_model: bool
    booking_status: str
    payment_status: str
    compliance_posture: str
    billable_hours: int
    required_bartender_count: int
    subtotal_cents: int
    service_fee_cents: int
    gratuity_cents: int
    provisional_grand_total_cents: int
    final_grand_total_cents: int
    deposit_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    cancelled_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict):
    id: str
    event_id: str
    abc_model: str
    liquor_liability_insurance_verified: bool
    host_alcohol_ownership_attested: bool
    server_certification_verified: bool
    revision_round: int
    reviewer_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    event_id: str
    bartender_id: str
    shift_start: str
    shift_end: str
    role_on_event: str
    shift_hours: float
    labor_cost_cents: int
    cancelled_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class KitReservation(TypedDict):
    id: str
    event_id: str
    kit_id: str
    reserve_start: str
    reserve_end: str
    items_checked_out: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryPlan(TypedDict):
    id: str
    event_id: str
    total_servings: int
    beer_units: int
    wine_bottles: int
    spirit_bottles: int
    ice_lbs: int
    glassware_needed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    event_id: str
    name: str
    drink_type: str
    spirit_base: str
    is_signature: bool
    abv_pct: float
    created_at: str
    updated_at: str
    version: int


# Payment is an immutable ledger record: id + created_at ONLY (PRD §2.4).
class Payment(TypedDict):
    id: str
    event_id: str
    payment_type: str
    amount_cents: int
    method: str
    created_at: str


class BreakageReport(TypedDict):
    id: str
    event_id: str
    kit_id: str
    items_broken: int
    items_returned: int
    items_checked_out: int
    breakage_fee_cents: int
    deposit_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
