"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TRUST_ADMIN = "TrustAdmin"
    EMPLOYER_REP = "EmployerRep"
    COMMITTEE_MEMBER = "CommitteeMember"
    INSTRUCTOR = "Instructor"


class FundPosture(str, Enum):
    OPERATING = "OPERATING"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class ProgramStatus(str, Enum):
    APPLICANT = "APPLICANT"
    INDENTURED = "INDENTURED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    UNFILED = "UNFILED"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    DEREGISTERED = "DEREGISTERED"


class RegistrationAgency(str, Enum):
    STATE = "STATE"
    FEDERAL = "FEDERAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FLAGGED = "FLAGGED"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"


class ClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    CREDITED = "CREDITED"
    NO_SHOW = "NO_SHOW"
    DROPPED = "DROPPED"


class PayBasis(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTUAL = "ACTUAL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class AllocationCategory(str, Enum):
    INSTRUCTION = "INSTRUCTION"
    EQUIPMENT = "EQUIPMENT"
    ADMIN = "ADMIN"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class PurchaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    PURCHASED = "PURCHASED"


# All nine primary resources carry the system-managed fields id, created_at,
# updated_at, and version (PRD §2.4).


class TrustFund(TypedDict):
    id: str
    name: str
    posture: str
    contributions_received_cents: int
    disbursed_cents: int
    allocated_remaining_cents: int
    available_cents: int
    delinquent_employer_count: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    trust_fund_id: str
    legal_name: str
    agreement_rate_cents_per_hour: int
    status: str
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Apprentice(TypedDict):
    id: str
    trust_fund_id: str
    employer_id: str
    full_name: str
    trade: str
    journeyman_base_rate_cents: int
    program_status: str
    registration_status: str
    registration_agency: Optional[str]
    ojt_hours_accumulated: float
    rti_credits_accumulated: int
    current_wage_step: int
    current_wage_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ContributionLine(TypedDict):
    apprentice_id: str
    ojt_hours: float


class ContributionReport(TypedDict):
    id: str
    employer_id: str
    period_year: int
    period_month: int
    lines: List[ContributionLine]
    due_date: str
    provisional_due_cents: int
    contribution_due_cents: Optional[int]
    flag_reason: Optional[str]
    status: str
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingClass(TypedDict):
    id: str
    trust_fund_id: str
    course_code: str
    instructor_user_id: str
    instructor_name: str
    instructor_rate_cents_per_hour: int
    facility: str
    rti_credit_value: int
    capacity: int
    enrolled_count: int
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassEnrollment(TypedDict):
    id: str
    class_id: str
    apprentice_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InstructorPayClaim(TypedDict):
    id: str
    class_id: str
    instructor_user_id: str
    pay_basis: str
    actual_minutes: Optional[int]
    payable_cents: int
    status: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    trust_fund_id: str
    category: str
    fiscal_year: int
    amount_cents: int
    encumbered_cents: int
    spent_cents: int
    remaining_cents: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentPurchase(TypedDict):
    id: str
    allocation_id: str
    description: str
    amount_cents: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
