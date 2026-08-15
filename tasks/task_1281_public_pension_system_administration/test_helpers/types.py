"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FUND_ADMIN = "FundAdmin"
    MEMBER_SERVICES_ANALYST = "MemberServicesAnalyst"
    BENEFIT_APPROVER = "BenefitApprover"
    MEDICAL_REVIEWER = "MedicalReviewer"
    EMPLOYER_CLERK = "EmployerClerk"
    MEMBER = "Member"
    SURVIVOR_CLAIMANT = "SurvivorClaimant"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RETIRED = "RETIRED"
    SUSPENDED_RTW = "SUSPENDED_RTW"
    DECEASED = "DECEASED"


class ContributionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VARIANCE = "VARIANCE"
    RECONCILED = "RECONCILED"


class ContributionLineStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ServicePurchaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PurchasePaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class RetirementApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class DisabilityApplicationStatus(str, Enum):
    UNDER_MEDICAL_REVIEW = "UNDER_MEDICAL_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class BenefitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BeneficiaryStatus(str, Enum):
    DESIGNATED = "DESIGNATED"
    REVOKED = "REVOKED"
    CLAIM_FILED = "CLAIM_FILED"
    PAYABLE = "PAYABLE"
    DENIED = "DENIED"


class PurchaseType(str, Enum):
    MILITARY = "MILITARY"
    PRIOR_SERVICE = "PRIOR_SERVICE"


class OptionElection(str, Enum):
    SINGLE_LIFE = "SINGLE_LIFE"
    JOINT_50 = "JOINT_50"
    JOINT_100 = "JOINT_100"


class DisabilityType(str, Enum):
    DUTY = "DUTY"
    NON_DUTY = "NON_DUTY"


class BenefitKind(str, Enum):
    SERVICE = "SERVICE"
    DISABILITY = "DISABILITY"


class CostVariant(str, Enum):
    FLAT = "FLAT"
    ACTUARIAL = "ACTUARIAL"


# Every persisted resource carries the full common field set — id, created_at,
# updated_at, version (PRD §2.4: no bare create-only records in this domain).

class PensionFund(TypedDict, total=False):
    id: str
    fund_name: str
    cola_rate_pct: float
    earnings_limit_annual_cents: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    name: str
    employer_code: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    hire_date: str
    status: str
    total_service_years: float
    current_annual_salary_cents: Optional[int]
    deceased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContributionReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    declared_total_cents: int
    accepted_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContributionLine(TypedDict, total=False):
    id: str
    fiscal_year: int
    period_salary_cents: int
    contribution_amount_cents: int
    service_months: int
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePurchase(TypedDict, total=False):
    id: str
    purchase_type: str
    service_period_start: str
    service_period_end: str
    years_purchased: float
    status: str
    flat_cost_cents: Optional[int]
    actuarial_cost_cents: Optional[int]
    cost_variant: Optional[str]
    quoted_cost_cents: Optional[int]
    quote_expires_at: Optional[str]
    installment_count: Optional[int]
    balance_due_cents: Optional[int]
    refunded_total_cents: int
    created_at: str
    updated_at: str
    version: int


class PurchasePayment(TypedDict, total=False):
    id: str
    sequence_number: int
    amount_cents: int
    due_date: str
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetirementApplication(TypedDict, total=False):
    id: str
    option_election: str
    beneficiary_name: Optional[str]
    beneficiary_date_of_birth: Optional[str]
    status: str
    provisional_monthly_cents: Optional[int]
    final_monthly_cents: Optional[int]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisabilityApplication(TypedDict, total=False):
    id: str
    disability_type: str
    description: Optional[str]
    status: str
    submitted_by_user_id: str
    last_reviewer_user_id: Optional[str]
    appeal_count: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Benefit(TypedDict, total=False):
    id: str
    benefit_kind: str
    monthly_amount_cents: int
    status: str
    effective_date: str
    cola_applied_count: int
    rtw_calendar_year: Optional[int]
    rtw_ytd_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    full_name: str
    relationship: str
    date_of_birth: str
    status: str
    claim_filed_at: Optional[str]
    survivor_monthly_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
