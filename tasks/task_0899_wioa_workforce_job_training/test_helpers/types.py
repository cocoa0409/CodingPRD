"""Domain types: entity TypedDicts, status enums, role enum (WIOA Workforce API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    STATE_ADMIN = "StateAdmin"
    CASE_MANAGER = "CaseManager"
    FISCAL_OFFICER = "FiscalOfficer"
    BUSINESS_SERVICES_REP = "BusinessServicesRep"


# --- Status / enum value sets ---
class FundingStream(str, Enum):
    ADULT = "ADULT"
    DISLOCATED_WORKER = "DISLOCATED_WORKER"
    YOUTH = "YOUTH"


class PriorityOfService(str, Enum):
    PRIORITY = "PRIORITY"
    NON_PRIORITY = "NON_PRIORITY"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class EnrollmentStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    EXITED = "EXITED"


class CareerPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    CLOSED = "CLOSED"


class ServiceTrack(str, Enum):
    TRAINING = "TRAINING"
    JOB_READY = "JOB_READY"
    OJT = "OJT"


class ETPLStatus(str, Enum):
    APPLIED = "APPLIED"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CredentialType(str, Enum):
    DEGREE = "DEGREE"
    CERTIFICATE = "CERTIFICATE"
    LICENSE = "LICENSE"
    NONE = "NONE"


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    OBLIGATED = "OBLIGATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    MILEAGE = "MILEAGE"
    CHILDCARE = "CHILDCARE"
    TOOLS = "TOOLS"
    OTHER = "OTHER"


class SupportiveStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class EmployerSize(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"


class OJTStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    PLACED = "PLACED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class LocalArea(TypedDict):
    id: str
    name: str
    program_year: int
    ita_budget_total_cents: int
    ita_individual_cap_cents: int
    supportive_annual_cap_cents: int
    ita_budget_available_cents: int
    ita_budget_obligated_cents: int
    ita_budget_expended_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    local_area_id: str
    full_name: str
    funding_stream: str
    veteran: bool
    low_income: bool
    basic_skills_deficient: bool
    priority_of_service: str
    eligibility_status: str
    enrollment_status: str
    exit_date: Optional[str]
    exit_exclusion: bool
    supportive_available_cents: int
    supportive_obligated_cents: int
    supportive_expended_cents: int
    credential_attained: bool
    msg_attained: bool
    created_at: str
    updated_at: str
    version: int


class CareerPlan(TypedDict):
    id: str
    participant_id: str
    goal_occupation: str
    service_track: str
    supportive_need_documented: bool
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingProvider(TypedDict):
    id: str
    local_area_id: str
    name: str
    etpl_status: str
    created_at: str
    updated_at: str
    version: int


class TrainingProgram(TypedDict):
    id: str
    provider_id: str
    name: str
    cip_code: str
    total_cost_cents: int
    credential_type: str
    in_demand: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ITAVoucher(TypedDict):
    id: str
    participant_id: str
    program_id: str
    career_plan_id: str
    authorized_cost_cents: int
    planned_start_date: str
    planned_end_date: str
    amount_obligated_cents: int
    amount_expended_cents: int
    credential_earned: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable ledger record: id + created_at only.
class ITADisbursement(TypedDict):
    id: str
    voucher_id: str
    amount_cents: int
    note: Optional[str]
    created_at: str


class SupportiveServicePayment(TypedDict):
    id: str
    participant_id: str
    service_type: str
    amount_cents: Optional[int]
    trips: Optional[List[int]]
    computed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    local_area_id: str
    name: str
    size: str
    max_concurrent_ojt_slots: int
    created_at: str
    updated_at: str
    version: int


class OJTContract(TypedDict):
    id: str
    employer_id: str
    participant_id: str
    reimbursement_rate: float
    wage_cents_per_hour: int
    planned_hours: int
    obligated_amount_cents: int
    amount_expended_cents: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JobReferral(TypedDict):
    id: str
    participant_id: str
    employer_id: str
    job_title: str
    offered_wage_cents_per_hour: Optional[int]
    placement_wage_cents_per_hour: Optional[int]
    placement_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
