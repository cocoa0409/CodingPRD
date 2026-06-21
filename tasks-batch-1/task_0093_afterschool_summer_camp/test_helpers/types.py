"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entity model and lifecycle states described in the PRD. Entities that
carry the full common field set (id, created_at, updated_at, version) are first-class
records; Payment, WeatherEvent, and AuditEntry are immutable and carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    GUARDIAN = "Guardian"
    PROGRAM_DIRECTOR = "ProgramDirector"
    BILLING_ADMIN = "BillingAdmin"


# --- Status enums ---
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CapacityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"


class WeatherState(str, Enum):
    NORMAL = "NORMAL"
    RAIN_ACTIVATED = "RAIN_ACTIVATED"


class AuthorizationFormType(str, Enum):
    MEDICAL = "MEDICAL"
    PICKUP = "PICKUP"


class AuthorizationFormStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class ScholarshipTier(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class ScholarshipStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class EnrollmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class ProgramType(str, Enum):
    AFTERSCHOOL = "AFTERSCHOOL"
    CAMP = "CAMP"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    WALLET = "WALLET"


# --- Entity TypedDicts (first-class records carry the full common field set) ---
class Guardian(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    home_zip: str
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    guardian_id: str
    first_name: str
    birth_date: str
    age_years: int
    household_size: int
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict):
    id: str
    child_id: str
    contact_name: str
    contact_phone: str
    relationship: str
    created_at: str
    updated_at: str
    version: int


class AuthorizationForm(TypedDict):
    id: str
    child_id: str
    form_type: str
    status: str
    medication_notes: Optional[str]
    authorized_pickup_names: List[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    program_type: str
    min_age: int
    max_age: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    program_id: str
    title: str
    age_group_min: int
    age_group_max: int
    age_as_of_date: str
    weekly_capacity: int
    base_weekly_tuition_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeeklyOffering(TypedDict):
    id: str
    session_id: str
    week_start: str
    enrolled_count: int
    waitlist_count: int
    capacity_state: str
    weather_state: str
    rain_alternate_offering_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScholarshipAward(TypedDict):
    id: str
    child_id: str
    tier: str
    status: str
    approved_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    child_id: str
    weekly_offering_id: str
    invoice_id: str
    status: str
    waitlist_rank: Optional[int]
    provisional_tuition_cents: int
    final_tuition_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    guardian_id: str
    billing_period: str
    status: str
    subtotal_cents: int
    sibling_discount_cents: int
    total_due_cents: int
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Immutable records: id + created_at only (no updated_at, no version) ---
class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    created_at: str


class WeatherEvent(TypedDict):
    id: str
    weekly_offering_id: str
    declared_at: str
    moved_enrollment_count: int
    created_at: str


class AuditEntry(TypedDict):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    created_at: str
