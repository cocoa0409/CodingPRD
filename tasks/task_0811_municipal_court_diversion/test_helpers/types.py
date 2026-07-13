"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    COURT_CLERK = "CourtClerk"
    JUDGE = "Judge"
    PROBATION_OFFICER = "ProbationOfficer"
    CASHIER = "Cashier"
    DEFENDANT = "Defendant"
    COURT_ADMIN = "CourtAdmin"


class CaseStatus(str, Enum):
    DOCKETED = "DOCKETED"
    ARRAIGNED = "ARRAIGNED"
    DIVERSION_GRANTED = "DIVERSION_GRANTED"
    FAILED_TO_COMPLY = "FAILED_TO_COMPLY"
    COMPLIED = "COMPLIED"
    DISMISSED = "DISMISSED"


class ChargeSeverity(str, Enum):
    INFRACTION = "INFRACTION"
    MISDEMEANOR = "MISDEMEANOR"


class ArraignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class PleaValue(str, Enum):
    GUILTY = "GUILTY"
    NOT_GUILTY = "NOT_GUILTY"
    NO_CONTEST = "NO_CONTEST"


class DiversionStatus(str, Enum):
    OFFERED = "OFFERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"


class SiteType(str, Enum):
    COMMUNITY_SERVICE = "COMMUNITY_SERVICE"
    EDUCATION_CLASS = "EDUCATION_CLASS"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class LedgerStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class InstallmentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    SUPERSEDED = "SUPERSEDED"


class WarrantStatus(str, Enum):
    ISSUED = "ISSUED"
    RECALLED = "RECALLED"


class ExpungementStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


# ---- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ----

class Defendant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    prior_diversion_count: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    defendant_id: str
    citation_number: str
    offense_date: str
    arraignment_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    case_id: str
    offense_code: str
    severity: str
    base_fine_amount: float
    is_diversion_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Courtroom(TypedDict):
    id: str
    name: str
    room_code: str
    changeover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Arraignment(TypedDict):
    id: str
    case_id: str
    courtroom_id: str
    scheduled_start: str
    scheduled_end: str
    plea: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversionAgreement(TypedDict):
    id: str
    case_id: str
    mandated_service_hours: float
    required_class_sessions: int
    program_fee: float
    program_deadline: str
    assigned_service_hours: float
    completed_service_hours: float
    completed_class_sessions: int
    provisional_compliance_pct: float
    final_compliance_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceSite(TypedDict):
    id: str
    name: str
    site_type: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class ServiceAssignment(TypedDict):
    id: str
    diversion_id: str
    service_site_id: str
    assignment_type: str
    required_hours: float
    session_start: str
    session_end: str
    completed_hours: float
    assigned_by_officer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerAccount(TypedDict):
    id: str
    case_id: str
    assessed_amount: float
    collected_amount: float
    balance: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallmentPlan(TypedDict):
    id: str
    ledger_account_id: str
    num_installments: int
    installment_amount: float
    final_installment_amount: float
    next_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Payment is an immutable ledger entry: only id + created_at (no updated_at, no version).
class Payment(TypedDict):
    id: str
    ledger_account_id: str
    amount: float
    allocated_fines: float
    allocated_court_fee: float
    allocated_surcharge: float
    allocated_program_fee: float
    reversed: bool
    created_at: str


class Warrant(TypedDict):
    id: str
    case_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AmnestyProgram(TypedDict):
    id: str
    name: str
    penalty_waiver_pct: float
    reinstatement_fee: float
    active_from: str
    active_to: str
    created_at: str
    updated_at: str
    version: int


class ExpungementReferral(TypedDict):
    id: str
    case_id: str
    eligible_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
