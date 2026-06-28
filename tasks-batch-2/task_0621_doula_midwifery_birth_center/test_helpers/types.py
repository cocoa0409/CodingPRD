"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Midwifery Birth Center PRD. Entities with the full common-field
set carry id + created_at + updated_at + version; CarePackage is the lone
configuration entity that carries only id + created_at (no version/updated_at).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    MIDWIFE = "Midwife"
    BILLING_CLERK = "BillingClerk"
    CENTER_ADMIN = "CenterAdmin"


# --- Status enums ---
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PackageType(str, Enum):
    BIRTH = "BIRTH"
    POSTPARTUM = "POSTPARTUM"
    COMBINED = "COMBINED"


class ProviderRoleType(str, Enum):
    MIDWIFE = "MIDWIFE"
    DOULA = "DOULA"


class ProviderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EpisodeClinicalStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    BORN = "BORN"
    COMPLETED = "COMPLETED"


class EpisodeFinancialStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    TRANSFER_REQUIRED = "TRANSFER_REQUIRED"


class VisitKind(str, Enum):
    PRENATAL = "PRENATAL"
    POSTPARTUM = "POSTPARTUM"
    LACTATION = "LACTATION"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RiskFlag(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    TRANSFER = "TRANSFER"


class CoverageRole(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ON_DUTY = "ON_DUTY"
    RELEASED = "RELEASED"
    PROMOTED = "PROMOTED"
    STOOD_DOWN = "STOOD_DOWN"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    VOID = "VOID"


class ChargeKind(str, Enum):
    GLOBAL_FEE = "GLOBAL_FEE"
    EXTRA_VISIT = "EXTRA_VISIT"
    SUPPLY = "SUPPLY"
    TRANSFER_FEE = "TRANSFER_FEE"


class ChargeStatus(str, Enum):
    DRAFT = "DRAFT"
    BILLED = "BILLED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentPlanStatus(str, Enum):
    OPEN = "OPEN"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---

# common_fields: true
class Client(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    parity: int
    insurance_payer: str
    policy_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — config entity, carries only id + created_at
class CarePackage(TypedDict):
    id: str
    code: str
    package_type: str
    global_fee_cents: int
    prenatal_visits_included: int
    postpartum_visits_included: int
    kit_sku: str
    created_at: str


# common_fields: true
class SupplyKit(TypedDict):
    id: str
    sku: str
    name: str
    on_hand_count: int
    reserved_count: int
    consumed_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Provider(TypedDict):
    id: str
    full_name: str
    role_type: str
    license_number: str
    max_active_episodes: int
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Room(TypedDict):
    id: str
    name: str
    turnover_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Episode(TypedDict):
    id: str
    client_id: str
    package_code: str
    edd: str
    clinical_status: str
    financial_status: str
    risk_tier: str
    kit_issued: bool
    prenatal_visits_completed: int
    global_fee_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class PrenatalVisit(TypedDict):
    id: str
    episode_id: str
    visit_kind: str
    scheduled_at: str
    status: str
    blood_pressure_systolic: Optional[int]
    risk_flag: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class OnCallAssignment(TypedDict):
    id: str
    episode_id: str
    provider_id: str
    coverage_start: str
    coverage_end: str
    backup_assignment_id: Optional[str]
    coverage_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Booking(TypedDict):
    id: str
    episode_id: str
    room_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class InsuranceClaim(TypedDict):
    id: str
    episode_id: str
    billed_amount_cents: int
    allowed_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Charge(TypedDict):
    id: str
    episode_id: str
    claim_id: str
    charge_kind: str
    amount_cents: int
    client_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class PaymentPlan(TypedDict):
    id: str
    episode_id: str
    total_cents: int
    installment_count: int
    paid_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
