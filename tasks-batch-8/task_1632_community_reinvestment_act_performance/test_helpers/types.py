"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CRA_OFFICER = "CRAOfficer"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    QUALIFICATION_REVIEWER = "QualificationReviewer"
    BANK_EXAMINER = "BankExaminer"
    BANK_EXECUTIVE = "BankExecutive"
    PLATFORM_ADMIN = "PlatformAdmin"


class AssessmentAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETIRED = "RETIRED"


class DemographicProfileStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class LoanRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    REPORTED = "REPORTED"


class LoanType(str, Enum):
    SMALL_BUSINESS = "SMALL_BUSINESS"
    SMALL_FARM = "SMALL_FARM"


class TractIncomeLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    MIDDLE = "MIDDLE"
    UPPER = "UPPER"


class CdActivityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class ActivityType(str, Enum):
    CD_LOAN = "CD_LOAN"
    QUALIFIED_INVESTMENT = "QUALIFIED_INVESTMENT"
    CD_SERVICE = "CD_SERVICE"


class PurposeCategory(str, Enum):
    AFFORDABLE_HOUSING = "AFFORDABLE_HOUSING"
    COMMUNITY_SERVICES_LMI = "COMMUNITY_SERVICES_LMI"
    ECONOMIC_DEVELOPMENT = "ECONOMIC_DEVELOPMENT"
    REVITALIZATION_STABILIZATION = "REVITALIZATION_STABILIZATION"


class AllocationMethod(str, Enum):
    FULL_COUNT = "FULL_COUNT"
    PRO_RATA = "PRO_RATA"


class ReviewDecision(str, Enum):
    QUALIFY = "QUALIFY"
    DISQUALIFY = "DISQUALIFY"


class BranchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class CommentChannel(str, Enum):
    WRITTEN_LETTER = "WRITTEN_LETTER"
    EMAIL = "EMAIL"
    PUBLIC_MEETING = "PUBLIC_MEETING"


class CommentSubject(str, Enum):
    LENDING = "LENDING"
    INVESTMENT = "INVESTMENT"
    SERVICE = "SERVICE"
    BRANCH_ACCESS = "BRANCH_ACCESS"
    OTHER = "OTHER"


class PublicCommentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PUBLISHED = "PUBLISHED"
    RESPONDED = "RESPONDED"


class PublicFilePosture(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ExamType(str, Enum):
    LARGE_BANK = "LARGE_BANK"
    INTERMEDIATE_SMALL_BANK = "INTERMEDIATE_SMALL_BANK"


class ExamCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DATA_COLLECTION = "DATA_COLLECTION"
    FIELDWORK = "FIELDWORK"
    PRELIMINARY_RATING = "PRELIMINARY_RATING"
    APPEALED = "APPEALED"
    FINALIZED = "FINALIZED"


class TestRating(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    SATISFACTORY = "SATISFACTORY"
    NEEDS_TO_IMPROVE = "NEEDS_TO_IMPROVE"
    SUBSTANTIAL_NONCOMPLIANCE = "SUBSTANTIAL_NONCOMPLIANCE"


class CompositeRating(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    SATISFACTORY = "SATISFACTORY"
    NEEDS_TO_IMPROVE = "NEEDS_TO_IMPROVE"
    SUBSTANTIAL_NONCOMPLIANCE = "SUBSTANTIAL_NONCOMPLIANCE"


class ApplicationType(str, Enum):
    BRANCH_OPENING = "BRANCH_OPENING"
    BRANCH_CLOSURE = "BRANCH_CLOSURE"
    MERGER = "MERGER"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class AssessmentArea(TypedDict):
    id: str
    area_code: str
    name: str
    msa_code: str
    state_code: str
    census_tracts: List[str]
    effective_start_date: str
    effective_end_date: Optional[str]
    annual_cd_budget_cents: int
    confirmed_loan_count: int
    qualified_cd_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DemographicProfile(TypedDict):
    id: str
    assessment_area_id: str
    data_year: int
    total_tracts: int
    low_income_tracts: int
    moderate_income_tracts: int
    total_population: int
    lmi_population: int
    median_family_income: int
    lmi_population_pct: float
    lmi_tract_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanRecord(TypedDict):
    id: str
    assessment_area_id: str
    loan_type: str
    loan_amount_cents: int
    borrower_gross_annual_revenue_cents: int
    action_date: str
    census_tract: str
    tract_income_level: str
    inside_assessment_area: bool
    small_revenue_flag: bool
    lmi_geography_flag: bool
    reporting_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunityDevelopmentActivity(TypedDict):
    id: str
    assessment_area_id: str
    activity_type: str
    amount_cents: int
    primary_purpose_category: str
    lmi_benefit_pct: float
    activity_date: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    disqualify_reason: Optional[str]
    allocation_method: Optional[str]
    qualified_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict):
    id: str
    branch_code: str
    assessment_area_id: str
    census_tract: str
    tract_income_level: str
    expansion_application_id: Optional[str]
    opened_date: Optional[str]
    closed_date: Optional[str]
    notice_posted_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    commenter_name: str
    channel: str
    subject_area: str
    content: str
    received_at: str
    response_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicFile(TypedDict):
    id: str
    bank_name: str
    branch_list_current: bool
    aa_list_current: bool
    disclosure_statement_present: bool
    pending_comment_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class ExamCycle(TypedDict):
    id: str
    exam_type: str
    evaluation_window_start: str
    evaluation_window_end: str
    performance_context_narrative: str
    lending_test_rating: Optional[str]
    investment_test_rating: Optional[str]
    service_test_rating: Optional[str]
    composite_points: Optional[float]
    composite_rating: Optional[str]
    appeal_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpansionApplication(TypedDict):
    id: str
    application_type: str
    target_assessment_area_id: str
    branch_code: Optional[str]
    branch_census_tract: Optional[str]
    branch_tract_income_level: Optional[str]
    linked_branch_id: Optional[str]
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
