"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INTAKE_CLERK = "IntakeClerk"
    SCREENING_OFFICER = "ScreeningOfficer"
    ASSIGNMENT_COORDINATOR = "AssignmentCoordinator"
    SUPERVISING_ATTORNEY = "SupervisingAttorney"
    ATTORNEY = "Attorney"


# ---- Status enums ----

class OfficeBudgetStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class RecoupmentBasis(str, Enum):
    SCHEDULE = "SCHEDULE"
    ACTUAL = "ACTUAL"


class AttorneyType(str, Enum):
    STAFF = "STAFF"
    PANEL = "PANEL"


class AttorneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_CAPACITY = "AT_CAPACITY"
    SUSPENDED = "SUSPENDED"


class ChargeClass(str, Enum):
    FELONY_A = "FELONY_A"
    FELONY_B = "FELONY_B"
    MISDEMEANOR = "MISDEMEANOR"
    JUVENILE = "JUVENILE"
    APPEAL = "APPEAL"


class CaseStatus(str, Enum):
    REFERRED = "REFERRED"
    SCREENED = "SCREENED"
    ASSIGNED = "ASSIGNED"
    DISPOSED = "DISPOSED"
    DENIED = "DENIED"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    PARTIAL = "PARTIAL"
    INELIGIBLE = "INELIGIBLE"


class WeightBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTUAL = "ACTUAL"


class ComplexityTier(str, Enum):
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    CAPITAL = "CAPITAL"


class DispositionType(str, Enum):
    DISMISSED = "DISMISSED"
    PLEA = "PLEA"
    ACQUITTAL = "ACQUITTAL"
    CONVICTION = "CONVICTION"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DECIDED = "DECIDED"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    PARTIAL = "PARTIAL"
    INELIGIBLE = "INELIGIBLE"


class ConflictResult(str, Enum):
    CLEAR = "CLEAR"
    CONFLICT = "CONFLICT"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REASSIGNED = "REASSIGNED"
    CLOSED = "CLOSED"


class EventType(str, Enum):
    ARRAIGNMENT = "ARRAIGNMENT"
    MOTION_HEARING = "MOTION_HEARING"
    PRETRIAL = "PRETRIAL"
    TRIAL = "TRIAL"
    SENTENCING = "SENTENCING"


class CourtEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VACATED = "VACATED"


class ServiceType(str, Enum):
    INVESTIGATOR = "INVESTIGATOR"
    EXPERT_PSYCH = "EXPERT_PSYCH"
    EXPERT_FORENSIC = "EXPERT_FORENSIC"


class ServiceRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"


class VoucherType(str, Enum):
    PANEL_FEE = "PANEL_FEE"
    SERVICE = "SERVICE"


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class RecoupmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PARTIALLY_COLLECTED = "PARTIALLY_COLLECTED"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"


# ---- Entity TypedDicts ----
# Entities with common_fields: true carry id, created_at, updated_at, version.

class DefenderOffice(TypedDict):
    id: str
    name: str
    annual_voucher_budget_cents: int
    recoupment_basis: str
    voucher_spent_cents: int
    budget_status: str
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict):
    id: str
    office_id: str
    name: str
    attorney_type: str
    bar_number: str
    hourly_rate_cents: int
    max_weighted_caseload: float
    current_weighted_load: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — configuration record, id + created_at only.
class Courtroom(TypedDict):
    id: str
    name: str
    courthouse: str
    created_at: str


class Case(TypedDict):
    id: str
    office_id: str
    defendant_name: str
    charge_class: str
    status: str
    eligibility_status: str
    case_weight: float
    weight_basis: str
    complexity_tier: str
    co_defendant_count: int
    assigned_attorney_id: Optional[str]
    disposition_type: Optional[str]
    disposition_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialScreening(TypedDict):
    id: str
    case_id: str
    household_income_cents: int
    household_size: int
    asset_value_cents: int
    status: str
    result: str
    contribution_amount_cents: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit artifact, id + created_at only.
class ConflictCheck(TypedDict):
    id: str
    case_id: str
    attorney_id: str
    co_defendant_names: List[str]
    result: str
    created_at: str


class Assignment(TypedDict):
    id: str
    case_id: str
    attorney_id: str
    assigned_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtEvent(TypedDict):
    id: str
    case_id: str
    attorney_id: str
    courtroom_id: str
    event_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    case_id: str
    service_type: str
    estimated_hours: float
    estimated_rate_cents: int
    authorized_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    case_id: str
    attorney_id: str
    service_request_id: Optional[str]
    voucher_type: str
    claimed_hours: float
    approved_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoupmentOrder(TypedDict):
    id: str
    case_id: str
    basis: str
    assessed_amount_cents: int
    collected_amount_cents: int
    status: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
