"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    AUTHORIZER_STAFF = "AuthorizerStaff"
    APPLICATION_REVIEWER = "ApplicationReviewer"
    BOARD_MEMBER = "BoardMember"
    APPEALS_OFFICER = "AppealsOfficer"
    SCHOOL_OPERATOR = "SchoolOperator"
    AUTHORIZER_ADMIN = "AuthorizerAdmin"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RubricCriterion(str, Enum):
    ACADEMIC_PLAN = "ACADEMIC_PLAN"
    FINANCE_PLAN = "FINANCE_PLAN"
    GOVERNANCE = "GOVERNANCE"
    OPERATIONS_PLAN = "OPERATIONS_PLAN"
    COMMUNITY_SUPPORT = "COMMUNITY_SUPPORT"


class CompositeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class SchoolStatus(str, Enum):
    PRE_OPENING = "PRE_OPENING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class Standing(str, Enum):
    GOOD = "GOOD"
    NOTICE = "NOTICE"
    PROBATION = "PROBATION"
    CRITICAL = "CRITICAL"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RENEWED = "RENEWED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TargetDomain(str, Enum):
    ACADEMIC = "ACADEMIC"
    FINANCIAL = "FINANCIAL"
    OPERATIONAL = "OPERATIONAL"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class LotteryStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SEALED = "SEALED"
    EXECUTED = "EXECUTED"
    CERTIFIED = "CERTIFIED"
    AUDIT_FAILED = "AUDIT_FAILED"
    CANCELLED = "CANCELLED"


class PreferenceCode(str, Enum):
    SIBLING = "SIBLING"
    DISTRICT_RESIDENT = "DISTRICT_RESIDENT"
    STAFF_CHILD = "STAFF_CHILD"


class PreferenceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EntryOutcome(str, Enum):
    ENTERED = "ENTERED"
    OFFERED = "OFFERED"
    WAITLISTED = "WAITLISTED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class NoticeLevel(str, Enum):
    NOTICE = "NOTICE"
    PROBATION = "PROBATION"
    REVOCATION_REVIEW = "REVOCATION_REVIEW"


class NoticeDomain(str, Enum):
    ACADEMIC = "ACADEMIC"
    FINANCIAL = "FINANCIAL"
    OPERATIONAL = "OPERATIONAL"
    COMPLIANCE = "COMPLIANCE"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    MOOT = "MOOT"


class PlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class DecisionOutcome(str, Enum):
    RENEWED = "RENEWED"
    RENEWED_WITH_CONDITIONS = "RENEWED_WITH_CONDITIONS"
    DENIED = "DENIED"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    FINAL = "FINAL"
    REVERTED = "REVERTED"


class ClosureReason(str, Enum):
    REVOCATION = "REVOCATION"
    NON_RENEWAL = "NON_RENEWAL"
    VOLUNTARY = "VOLUNTARY"


class ClosureStatus(str, Enum):
    INITIATED = "INITIATED"
    TRANSITION_IN_PROGRESS = "TRANSITION_IN_PROGRESS"
    RECORDS_COMPLETE = "RECORDS_COMPLETE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TransitionStatus(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    RECORDS_SENT = "RECORDS_SENT"


class InvoiceStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class BilledVariant(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"


class AppealTargetType(str, Enum):
    APPLICATION_DENIAL = "APPLICATION_DENIAL"
    RENEWAL_DENIAL = "RENEWAL_DENIAL"
    REVOCATION = "REVOCATION"
    FEE_INVOICE = "FEE_INVOICE"


class AppealStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    RULED_UPHELD = "RULED_UPHELD"
    RULED_OVERTURNED = "RULED_OVERTURNED"


class AppealRuling(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


# ---------------------------------------------------------------------------
# Entity records (PRD §2.4: every resource carries id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------
class ReviewScore(TypedDict):
    reviewer_user_id: str
    criterion: str
    score: float


class CharterApplication(TypedDict):
    id: str
    school_name: str
    founding_group: str
    cycle_year: int
    proposed_grades: str
    review_scores: List[ReviewScore]
    rubric_complete: bool
    rubric_score: Optional[float]
    interview_score: Optional[float]
    composite_score: Optional[float]
    composite_variant: str
    status: str
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityInterview(TypedDict):
    id: str
    application_id: str
    scheduled_start: str
    scheduled_end: str
    panelist_user_ids: List[str]
    panel_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    application_id: str
    school_name: str
    status: str
    academic_standing: str
    financial_standing: str
    operational_standing: str
    current_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CharterContract(TypedDict):
    id: str
    school_id: str
    prior_contract_id: Optional[str]
    framework_version: str
    term_start: str
    term_end: str
    status: str
    targets_weight_total: float
    created_at: str
    updated_at: str
    version: int


class PerformanceTarget(TypedDict):
    id: str
    contract_id: str
    domain: str
    metric_code: str
    target_value: float
    floor_value: float
    weight: float
    created_at: str
    updated_at: str
    version: int


class MonitoringReport(TypedDict):
    id: str
    school_id: str
    fiscal_year: int
    academic_score: float
    financial_score: float
    operational_score: float
    compliance_index: float
    submitted_by_user_id: str
    return_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lottery(TypedDict):
    id: str
    school_id: str
    academic_year: int
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotteryEntry(TypedDict):
    id: str
    lottery_id: str
    student_ref: str
    grade_level: str
    preference_codes: List[str]
    preference_status: str
    preference_verified_by: Optional[str]
    outcome: str
    rank_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InterventionNotice(TypedDict):
    id: str
    school_id: str
    level: str
    domain: str
    reason: str
    issued_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    corrective_due_date: Optional[str]
    successor_notice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    intervention_id: str
    plan_text: str
    submitted_at: str
    reviewed_by_user_id: Optional[str]
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalDecision(TypedDict):
    id: str
    school_id: str
    contract_id: str
    eligible_term_years: int
    decision: Optional[str]
    granted_term_years: Optional[int]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosurePlan(TypedDict):
    id: str
    school_id: str
    reason: str
    closure_date: str
    decided_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StudentTransition(TypedDict):
    id: str
    closure_plan_id: str
    student_ref: str
    destination_school: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    school_id: str
    fiscal_year: int
    estimated_enrollment: int
    audited_enrollment: Optional[int]
    base_per_pupil_cents: int
    qualifying_supplemental_pupils: int
    base_funding_cents: int
    supplemental_cents: int
    total_funding_cents: int
    fee_rate: float
    billed_amount_cents: int
    billed_variant: str
    paid_cents: int
    waived_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    school_id: Optional[str]
    target_type: str
    target_id: str
    grounds: str
    filed_by_user_id: str
    filed_at: str
    hearing_officer_user_id: Optional[str]
    ruling: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
