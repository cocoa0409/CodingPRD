"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    FRONT_DESK_AGENT = "FrontDeskAgent"
    ACCESS_SUPERVISOR = "AccessSupervisor"


class PatientStatus(str, Enum):
    PRE_REGISTERED = "PRE_REGISTERED"
    REGISTERED = "REGISTERED"
    MERGED = "MERGED"
    INACTIVE = "INACTIVE"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    VOIDED = "VOIDED"


class PlanType(str, Enum):
    HMO = "HMO"
    PPO = "PPO"
    EPO = "EPO"
    POS = "POS"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    SELF_PAY = "SELF_PAY"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class EligibilityResult(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_AUTH = "VERIFIED_WITH_AUTH"
    FAILED = "FAILED"
    STALE = "STALE"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class AuthorizationStatus(str, Enum):
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PRE_CHECKED = "PRE_CHECKED"
    READY = "READY"
    ARRIVED = "ARRIVED"
    IN_ROOM = "IN_ROOM"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RegistrationGate(str, Enum):
    CLEAR = "CLEAR"
    CLEAR_WITH_PAYMENT = "CLEAR_WITH_PAYMENT"
    BLOCKED = "BLOCKED"


class VisitType(str, Enum):
    NEW = "NEW"
    ESTABLISHED = "ESTABLISHED"
    PROCEDURE = "PROCEDURE"
    IMAGING = "IMAGING"


class EstimateMethod(str, Enum):
    PAYER_VERIFIED = "PAYER_VERIFIED"
    FEE_SCHEDULE = "FEE_SCHEDULE"


class EstimateStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    CHECK = "CHECK"
    WALLET = "WALLET"


class PaymentKind(str, Enum):
    POST = "POST"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class TicketState(str, Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    SERVED = "SERVED"
    SKIPPED = "SKIPPED"
    REMOVED = "REMOVED"


class TicketPriority(str, Enum):
    STAT = "STAT"
    ACCOMMODATION = "ACCOMMODATION"
    STANDARD = "STANDARD"


class FlagType(str, Enum):
    INTERPRETER = "INTERPRETER"
    MOBILITY = "MOBILITY"
    SENSORY = "SENSORY"
    COGNITIVE = "COGNITIVE"


# All resources carry the common properties of PRD §2.4:
# id, created_at, updated_at, version.


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: str
    sex_at_birth: str
    primary_phone: str
    email: Optional[str]
    language_code: str
    duplicate_of_patient_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    patient_id: str
    payer_id: str
    member_id: str
    group_number: Optional[str]
    plan_type: str
    effective_start: str
    effective_end: Optional[str]
    priority_rank: int
    deductible_remaining_cents: int
    oop_max_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityCheck(TypedDict, total=False):
    id: str
    policy_id: str
    appointment_id: str
    checked_at: str
    coverage_status: str
    copay_cents: int
    coinsurance_pct: int
    auth_required: bool
    result: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    patient_id: str
    referring_provider_npi: str
    specialty_code: str
    procedure_code: str
    visits_authorized: int
    visits_consumed: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict, total=False):
    id: str
    patient_id: str
    appointment_id: str
    payer_auth_number: str
    authorized_units: int
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    patient_id: str
    referring_provider_npi: Optional[str]
    department_code: str
    procedure_code: str
    scheduled_start: str
    duration_minutes: int
    visit_type: str
    provider_code: str
    status: str
    registration_gate: str
    estimated_patient_responsibility_cents: int
    amount_collected_cents: int
    auth_satisfied: bool
    referral_id: Optional[str]
    late_minutes: int
    no_show_risk_strikes: int
    created_at: str
    updated_at: str
    version: int


class CopayEstimate(TypedDict, total=False):
    id: str
    appointment_id: str
    policy_id: str
    method: str
    allowed_amount_cents: int
    estimated_patient_responsibility_cents: int
    deposit_required_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    appointment_id: str
    amount_cents: int
    method: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict, total=False):
    id: str
    appointment_id: str
    department_code: str
    queue_date: str
    sequence_number: int
    priority: str
    state: str
    called_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationFlag(TypedDict, total=False):
    id: str
    patient_id: str
    flag_type: str
    language_code: Optional[str]
    note: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int
