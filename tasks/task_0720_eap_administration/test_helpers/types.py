"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CARE_COORDINATOR = "CareCoordinator"
    CRISIS_COUNSELOR = "CrisisCounselor"
    PROVIDER = "Provider"
    EMPLOYER = "Employer"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    GRACE = "GRACE"
    INELIGIBLE = "INELIGIBLE"


class DependentRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    OTHER = "OTHER"


class PresentingIssue(str, Enum):
    STRESS = "STRESS"
    RELATIONSHIP = "RELATIONSHIP"
    SUBSTANCE = "SUBSTANCE"
    GRIEF = "GRIEF"
    FINANCIAL_STRESS = "FINANCIAL_STRESS"
    OTHER = "OTHER"


class CaseClinicalStatus(str, Enum):
    INTAKE = "INTAKE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CaseFundingStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ReferralType(str, Enum):
    CLINICAL = "CLINICAL"
    WORKLIFE = "WORKLIFE"
    LEGAL = "LEGAL"
    FINANCIAL = "FINANCIAL"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DENIED = "DENIED"


class CrisisSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMINENT = "IMMINENT"


class CrisisStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class CrisisDisposition(str, Enum):
    SELF_HELP = "SELF_HELP"
    ROUTINE_REFERRAL = "ROUTINE_REFERRAL"
    URGENT_REFERRAL = "URGENT_REFERRAL"
    EMERGENCY_DISPATCH = "EMERGENCY_DISPATCH"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESUBMITTED = "RESUBMITTED"
    PAID = "PAID"


class WellnessActivityType(str, Enum):
    SCREENING = "SCREENING"
    WEBINAR = "WEBINAR"
    CHALLENGE = "CHALLENGE"
    COACHING = "COACHING"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class EmployerContract(TypedDict):
    id: str
    employer_name: str
    sessions_per_issue: int
    annual_session_cap: int
    crisis_sla_minutes: int
    session_rate_cents: int
    annual_reimbursement_budget_cents: int
    reporting_min_cohort: int
    status: str
    sessions_committed: int
    utilization_rate: float
    created_at: str
    updated_at: str
    version: int


class BenefitPlan(TypedDict):
    id: str
    contract_id: str
    name: str
    worklife_referrals_per_year: int
    copay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    contract_id: str
    plan_id: str
    full_name: str
    external_ref: str
    eligibility_status: str
    grace_until: Optional[str]
    worklife_referrals_used: int
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict):
    id: str
    employee_id: str
    full_name: str
    relationship: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    contract_id: str
    employee_id: str
    dependent_id: Optional[str]
    presenting_issue: str
    clinical_status: str
    funding_status: str
    session_allotment: int
    sessions_used: int
    sessions_remaining: int
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    case_id: str
    provider_id: str
    scheduled_for: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    network_status: str
    specialties: List[str]
    accepting: bool
    active_referral_count: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    case_id: Optional[str]
    employee_id: str
    provider_id: Optional[str]
    referral_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrisisContact(TypedDict):
    id: str
    contract_id: str
    employee_id: Optional[str]
    opened_at: str
    severity: str
    triaged_at: Optional[str]
    sla_breached: bool
    status: str
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    contract_id: str
    session_id: str
    provider_id: str
    billed_cents: int
    provisional_cents: int
    final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessActivity(TypedDict):
    id: str
    employee_id: str
    activity_type: str
    points: int
    completed_on: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only snapshot, carries ONLY id + created_at
class UtilizationReport(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    total_cases: int
    distinct_employees: int
    issue_breakdown: dict
    suppressed: bool
    created_at: str
