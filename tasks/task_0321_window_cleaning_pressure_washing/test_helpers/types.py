"""Domain types: entity TypedDicts, status enums, role enum.

Entities carrying the common system fields (id, created_at, updated_at, version)
are modeled with all four. VisitPhoto and LedgerEntry are append-only records
(PRD §2.4): they carry only id and created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, List


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    FIELD_CREW = "FieldCrew"
    BILLING = "Billing"


# ─── Region / shared enums ───────────────────────────────────────────────
class RegionCode(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


# ─── Status enums ────────────────────────────────────────────────────────
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"


class ServiceAgreementStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class VisitScheduleStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ReCleanRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class DepositStatus(str, Enum):
    HELD = "HELD"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class PricingBasis(str, Enum):
    PANE_COUNT = "PANE_COUNT"
    SQ_FT = "SQ_FT"


class AddonCode(str, Enum):
    GUTTER = "GUTTER"
    SCREEN = "SCREEN"
    SOFT_WASH = "SOFT_WASH"


class SkillCode(str, Enum):
    SOFT_WASH = "SOFT_WASH"
    HIGH_RISE = "HIGH_RISE"


class PhotoPhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class ScheduleKind(str, Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"


class WeatherSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    SUSPEND = "SUSPEND"


class LedgerSourceType(str, Enum):
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"
    DEPOSIT = "DEPOSIT"
    RECLEAN_CREDIT = "RECLEAN_CREDIT"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──
class Account(TypedDict):
    id: str
    company_name: str
    contact_email: str
    region_code: str
    balance_cents: int
    deposit_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    account_id: str
    address_line: str
    pane_count: int
    glass_sqft: float
    stories: int
    soft_wash_sqft: float
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    account_id: str
    property_id: str
    pricing_basis: str
    addon_codes: List[str]
    base_price_cents: int
    addon_total_cents: int
    quoted_total_cents: int
    required_deposit_cents: int
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict):
    id: str
    account_id: str
    property_id: str
    quote_id: str
    schedule_kind: str
    recurrence_interval_days: int
    per_visit_price_cents: int
    required_deposit_cents: int
    visits_generated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_name: str
    region_code: str
    skill_codes: List[str]
    daily_capacity_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    crew_id: str
    region_code: str
    service_date: str
    booked_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    agreement_id: str
    property_id: str
    route_id: str
    planned_date: str
    window_start_min: int
    window_end_min: int
    duration_minutes: int
    requires_soft_wash: bool
    requires_high_rise: bool
    reschedule_count: int
    charge_amount_cents: int
    schedule_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class VisitAddOn(TypedDict):
    id: str
    visit_id: str
    addon_code: str
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ReCleanRequest(TypedDict):
    id: str
    visit_id: str
    reason: str
    remedy_visit_id: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    visit_id: str
    amount_cents: int
    deposit_applied_cents: int
    net_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    account_id: str
    agreement_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherAdvisory(TypedDict):
    id: str
    region_code: str
    advisory_date: str
    severity: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (common_fields: false → id + created_at only) ──────
class VisitPhoto(TypedDict):
    id: str
    visit_id: str
    phase: str
    image_uri: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    account_id: str
    source_type: str
    source_id: str
    signed_amount_cents: int
    created_at: str
