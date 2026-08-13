"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ACCREDITATION_OFFICER = "AccreditationOfficer"
    ACCREDITATION_COMMISSION = "AccreditationCommission"
    SCHOOL_LEADER = "SchoolLeader"
    REVIEWER = "Reviewer"
    SYSTEM_BURSAR = "SystemBursar"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class AccreditationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACCREDITED = "ACCREDITED"
    ON_PROBATION = "ON_PROBATION"
    ACCREDITATION_WITHDRAWN = "ACCREDITATION_WITHDRAWN"


class SystemType(str, Enum):
    DISTRICT = "DISTRICT"
    NETWORK = "NETWORK"
    SINGLE_SCHOOL = "SINGLE_SCHOOL"


class CampusStatus(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    WITHDRAWN = "WITHDRAWN"


class StandardDomain(str, Enum):
    LEADERSHIP = "LEADERSHIP"
    LEARNING = "LEARNING"
    RESOURCES = "RESOURCES"


class TermStatus(str, Enum):
    PREPARATION = "PREPARATION"
    SELF_STUDY = "SELF_STUDY"
    REVIEW = "REVIEW"
    DECISION = "DECISION"
    TERM_ACTIVE = "TERM_ACTIVE"
    INTERIM_MONITORING = "INTERIM_MONITORING"
    RENEWAL = "RENEWAL"
    CLOSED = "CLOSED"


class DecisionOutcome(str, Enum):
    NONE = "NONE"
    ACCREDITED = "ACCREDITED"
    ACCREDITED_WITH_STIPULATIONS = "ACCREDITED_WITH_STIPULATIONS"
    DENIED = "DENIED"


class RatingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"


class EvidenceReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class StakeholderGroup(str, Enum):
    STUDENTS = "STUDENTS"
    PARENTS = "PARENTS"
    STAFF = "STAFF"
    BOARD = "BOARD"


class SurveyWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


class GoalDirection(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class GoalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    MONITORING = "MONITORING"
    ACHIEVED = "ACHIEVED"
    ABANDONED = "ABANDONED"


class VisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_FIELD = "IN_FIELD"
    REPORT_DRAFT = "REPORT_DRAFT"
    REPORT_ISSUED = "REPORT_ISSUED"
    CANCELLED = "CANCELLED"


class ReviewerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"
    INACTIVE = "INACTIVE"


class TeamRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"
    OBSERVER = "OBSERVER"


class FindingSeverity(str, Enum):
    COMMENDATION = "COMMENDATION"
    RECOMMENDATION = "RECOMMENDATION"
    REQUIRED_ACTION = "REQUIRED_ACTION"


class FindingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class ActionItemStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class InterimReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    LATE = "LATE"


class InvoiceType(str, Enum):
    ANNUAL_FEE = "ANNUAL_FEE"
    VISIT_FEE = "VISIT_FEE"
    RENEWAL_FEE = "RENEWAL_FEE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; §3 entity fields)
# ---------------------------------------------------------------------------

class InstitutionSystem(TypedDict, total=False):
    id: str
    name: str
    system_type: str
    accreditation_status: str
    current_term_id: Optional[str]
    fee_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Campus(TypedDict, total=False):
    id: str
    system_id: str
    name: str
    enrollment: int
    campus_status: str
    composite_index_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Standard(TypedDict, total=False):
    # Lightweight record (PRD §2.4): id + created_at only, no updated_at/version.
    id: str
    code: str
    title: str
    domain: str
    weight_pct: int
    evidence_min_items: int
    created_at: str


class AccreditationTerm(TypedDict, total=False):
    id: str
    system_id: str
    term_start: str
    term_length_years: int
    term_end: str
    status: str
    decision_outcome: str
    created_at: str
    updated_at: str
    version: int


class SelfStudyRating(TypedDict, total=False):
    id: str
    term_id: str
    campus_id: str
    standard_id: str
    rating: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    rating_id: str
    title: str
    artifact_uri: str
    submitted_by_user_id: str
    review_status: str
    created_at: str
    updated_at: str
    version: int


class SurveyInstrument(TypedDict, total=False):
    id: str
    stakeholder_group: str
    title: str
    min_participation_pct: int
    created_at: str
    updated_at: str
    version: int


class SurveyWindow(TypedDict, total=False):
    id: str
    term_id: str
    campus_id: str
    instrument_id: str
    opens_at: str
    closes_at: str
    eligible_count: int
    response_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict, total=False):
    # Lightweight record (PRD §2.4): id + created_at only.
    id: str
    window_id: str
    respondent_token: str
    submitted_at: str
    created_at: str


class ImprovementGoal(TypedDict, total=False):
    id: str
    term_id: str
    campus_id: Optional[str]
    standard_id: str
    title: str
    baseline_value: float
    target_value: float
    direction: str
    current_value: float
    attainment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressIndicator(TypedDict, total=False):
    id: str
    goal_id: str
    measured_at: str
    value: float
    note: str
    created_at: str
    updated_at: str
    version: int


class VisitEvent(TypedDict, total=False):
    id: str
    term_id: str
    campus_id: Optional[str]
    lead_reviewer_id: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    reviewer_status: str
    conflict_system_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class VisitAssignment(TypedDict, total=False):
    id: str
    visit_id: str
    reviewer_id: str
    role_on_team: str
    created_at: str
    updated_at: str
    version: int


class VisitFinding(TypedDict, total=False):
    id: str
    visit_id: str
    standard_id: str
    severity: str
    follow_up_months: Optional[int]
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RequiredActionItem(TypedDict, total=False):
    id: str
    finding_id: str
    description: str
    due_date: str
    follow_up_months: int
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterimReport(TypedDict, total=False):
    id: str
    term_id: str
    report_year: int
    due_date: str
    narrative: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    # Lightweight record (PRD §2.4): id + created_at only.
    id: str
    effective_from: str
    base_system_fee_cents: int
    per_campus_fee_cents: int
    large_campus_fee_cents: int
    large_campus_threshold: int
    visit_day_rate_cents: int
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    system_id: str
    billing_year: int
    invoice_type: str
    amount_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Lightweight record (PRD §2.4): id + created_at only.
    id: str
    invoice_id: str
    amount_cents: int
    paid_at: str
    created_at: str
