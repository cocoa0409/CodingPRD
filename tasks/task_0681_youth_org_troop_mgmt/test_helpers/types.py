"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values mirror the PRD's resource definitions exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    COUNCIL_REGISTRAR = "CouncilRegistrar"
    TROOP_LEADER = "TroopLeader"


# --------------------------------------------------------------------------- enums
class TroopCharterStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CHARTERED = "CHARTERED"
    LAPSED = "LAPSED"
    DROPPED = "DROPPED"


class RecharterPosture(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class ProgramType(str, Enum):
    CUB = "CUB"
    SCOUTS = "SCOUTS"
    VENTURING = "VENTURING"


class MemberType(str, Enum):
    YOUTH = "YOUTH"
    ADULT = "ADULT"


class Rank(str, Enum):
    SCOUT = "SCOUT"
    TENDERFOOT = "TENDERFOOT"
    SECOND_CLASS = "SECOND_CLASS"
    FIRST_CLASS = "FIRST_CLASS"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    DROPPED = "DROPPED"


class DuesInvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"


class BgcheckStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class TrainingStatus(str, Enum):
    UNTRAINED = "UNTRAINED"
    TRAINED = "TRAINED"


class AdvancementKind(str, Enum):
    RANK = "RANK"
    BADGE = "BADGE"


class AdvancementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class PermissionStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"


class HealthStatus(str, Enum):
    MISSING = "MISSING"
    ON_FILE = "ON_FILE"


class EventRegistrationStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class FundraiserProduct(str, Enum):
    COOKIES = "COOKIES"
    POPCORN = "POPCORN"


class FundraiserStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    CLOSED = "CLOSED"


class FundraiserOrderStatus(str, Enum):
    PLACED = "PLACED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class BoothReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class LedgerAccount(str, Enum):
    COUNCIL_CASH = "COUNCIL_CASH"
    PRODUCT_LIABILITY = "PRODUCT_LIABILITY"
    TROOP_DUES = "TROOP_DUES"


class LedgerSourceKind(str, Enum):
    PAYMENT = "PAYMENT"
    FUNDRAISER_ORDER = "FUNDRAISER_ORDER"
    RECHARTER = "RECHARTER"
    REVERSAL = "REVERSAL"


# --------------------------------------------------------------------------- entities
# Entities carrying the full common-field set (id, created_at, updated_at, version).
class Council(TypedDict):
    id: str
    name: str
    charter_fee_cents: int
    youth_dues_cents: int
    adult_dues_cents: int
    fund_cash_cents: int
    fund_liability_cents: int
    program_year: int
    created_at: str
    updated_at: str
    version: int


class Troop(TypedDict):
    id: str
    council_id: str
    unit_number: str
    program_type: str
    charter_status: str
    recharter_posture: str
    registered_youth_count: int
    cleared_leader_count: int
    charter_expires_at: Optional[str]
    dues_account_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    troop_id: str
    member_type: str
    full_name: str
    birthdate: str
    rank: str
    registration_status: str
    dues_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict):
    id: str
    member_id: str
    troop_id: str
    amount_cents: int
    issued_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaderCredential(TypedDict):
    id: str
    member_id: str
    requested_by_user_id: str
    bgcheck_status: str
    training_status: str
    training_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advancement(TypedDict):
    id: str
    member_id: str
    kind: str
    target: str
    badge_code: Optional[str]
    requirements_total: int
    requirements_signed: int
    completion_pct: float
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    troop_id: str
    title: str
    starts_at: str
    ends_at: str
    requires_health_form: bool
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    event_id: str
    member_id: str
    permission_status: str
    health_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Fundraiser(TypedDict):
    id: str
    council_id: str
    product: str
    unit_price_cents: int
    unit_cost_cents: int
    total_inventory_units: int
    allocated_units: int
    available_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundraiserOrder(TypedDict):
    id: str
    fundraiser_id: str
    troop_id: str
    seller_member_id: str
    units: int
    gross_cents: int
    troop_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoothReservation(TypedDict):
    id: str
    fundraiser_id: str
    troop_id: str
    location_code: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only records — id + created_at ONLY (no updated_at, no version).
class Payment(TypedDict):
    id: str
    invoice_id: str
    member_id: str
    amount_cents: int
    status: str
    created_at: str


class FundLedgerEntry(TypedDict):
    id: str
    council_id: str
    troop_id: Optional[str]
    account: str
    amount_cents: int
    source_kind: str
    source_ref_id: str
    created_at: str
