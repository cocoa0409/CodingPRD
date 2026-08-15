"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRODUCER_REP = "ProducerRep"
    UNION_REP = "UnionRep"
    FUND_TRUSTEE = "FundTrustee"
    ARBITRATOR = "Arbitrator"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProducerCompanyStatus(str, Enum):
    PENDING = "PENDING"
    SIGNATORY = "SIGNATORY"
    SUSPENDED = "SUSPENDED"


class SignatoryApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AgreementTier(str, Enum):
    ULTRA_LOW_BUDGET = "ULTRA_LOW_BUDGET"
    MODIFIED_LOW_BUDGET = "MODIFIED_LOW_BUDGET"
    LOW_BUDGET = "LOW_BUDGET"
    BASIC = "BASIC"


class ProductionStatus(str, Enum):
    REGISTERED = "REGISTERED"
    STAFFING = "STAFFING"
    IN_PRODUCTION = "IN_PRODUCTION"
    SUSPENDED = "SUSPENDED"
    WRAPPED = "WRAPPED"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    UNDERFUNDED = "UNDERFUNDED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class CrewAssignmentStatus(str, Enum):
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"
    TERMINATED = "TERMINATED"


class WorkDayLogStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    PROPOSED_SETTLEMENT = "PROPOSED_SETTLEMENT"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class ProposalStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ContributionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class ForceMajeureEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ProducerCompany(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    status: str
    signatory_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SignatoryApplication(TypedDict, total=False):
    id: str
    producer_company_id: str
    requested_agreement_scope: str
    estimated_slate_budget_cents: int
    status: str
    review_rounds: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    producer_company_id: str
    title: str
    agreement_tier: str
    budget_cents: int
    status: str
    pre_suspension_status: Optional[str]
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict, total=False):
    id: str
    production_id: str
    amount_required_cents: int
    amount_held_cents: int
    total_posted_cents: int
    total_released_cents: int
    total_forfeited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    production_id: str
    crew_member_ref: str
    department: str
    classification: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkDayLog(TypedDict, total=False):
    id: str
    crew_assignment_id: str
    work_date: str
    call_time_minutes: int
    wrap_time_minutes: int
    meal_breaks: List[dict]
    meal_penalty_units: int
    meal_penalty_cents: int
    turnaround_violation: bool
    turnaround_penalty_cents: int
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict, total=False):
    id: str
    production_id: str
    crew_assignment_id: Optional[str]
    category: str
    incident_date: str
    description: str
    filed_by_user_id: str
    intake_user_id: Optional[str]
    proposal_amount_cents: Optional[int]
    proposal_status: str
    settlement_agreed_cents: int
    settlement_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContributionReport(TypedDict, total=False):
    id: str
    production_id: str
    period_index: int
    work_day_log_ids: List[str]
    provisional_gross_wages_cents: int
    provisional_contributions_due_cents: int
    final_gross_wages_cents: Optional[int]
    final_contributions_due_cents: Optional[int]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    production_id: str
    scope_period_indices: List[int]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    assessment_cents: Optional[int]
    alt_assessment_cents: Optional[int]
    assessment_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForceMajeureEvent(TypedDict, total=False):
    id: str
    production_id: str
    event_type: str
    start_date: str
    end_date: Optional[str]
    lifted_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
