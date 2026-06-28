"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    FIELD_TECH = "FieldTech"
    CUSTOMER = "Customer"
    BILLING_ADMIN = "BillingAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InsuranceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SoilingLevel(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class SurfaceType(str, Enum):
    ROOF = "ROOF"
    SIDING = "SIDING"
    CONCRETE = "CONCRETE"


class ServiceType(str, Enum):
    ROOF_SOFT_WASH = "ROOF_SOFT_WASH"
    HOUSE_WASH = "HOUSE_WASH"
    CONCRETE_CLEAN = "CONCRETE_CLEAN"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RECLEAN_REQUESTED = "RECLEAN_REQUESTED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class WeatherCondition(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class PhotoPhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --- Primary entities (carry id, created_at, updated_at, version) ---

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    ladder_cert_max_stories: int
    insurance_status: str
    scheduled_minutes: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    name: str
    travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    customer_id: str
    route_id: str
    address: str
    stories: int
    roof_sqft: int
    siding_sqft: int
    concrete_sqft: int
    created_at: str
    updated_at: str
    version: int


class ServiceQuote(TypedDict):
    id: str
    property_id: str
    soiling_level: str
    subtotal_cents: Optional[int]
    travel_surcharge_cents: Optional[int]
    total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringPlan(TypedDict):
    id: str
    property_id: str
    source_quote_id: str
    cadence_days: int
    next_due_utc: str
    visits_generated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    property_id: str
    quote_id: Optional[str]
    plan_id: Optional[str]
    route_id: str
    scheduled_date: str
    duration_minutes: int
    provisional_cost_cents: Optional[int]
    final_cost_cents: Optional[int]
    reclean_of_visit_id: Optional[str]
    billing_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    visit_id: str
    technician_id: str
    window_start_utc: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherWindow(TypedDict):
    id: str
    route_id: str
    window_start_utc: str
    window_end_utc: str
    wind_mph: int
    condition: str
    precip_flag: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    visit_id: str
    customer_id: str
    amount_due_cents: int
    loyalty_discount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SatisfactionClaim(TypedDict):
    id: str
    visit_id: str
    reason: str
    reclean_visit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only evidence rows (carry ONLY id + created_at) ---

class QuoteLineItem(TypedDict):
    id: str
    quote_id: str
    surface_type: str
    service_type: str
    measured_sqft: int
    chemical_dose_oz: float
    line_total_cents: int
    created_at: str


class PhotoSet(TypedDict):
    id: str
    visit_id: str
    phase: str
    photo_url: str
    created_at: str
