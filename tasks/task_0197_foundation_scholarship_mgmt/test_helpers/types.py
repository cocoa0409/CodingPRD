"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields are drawn from the Foundation Scholarship Management PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    FOUNDATION_ADMIN = "FoundationAdmin"
    APPLICANT = "Applicant"
    COMMITTEE_MEMBER = "CommitteeMember"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"


# --- Status enums ---
class FundStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REVIEW = "REVIEW"
    AWARDING = "AWARDING"
    CLOSED = "CLOSED"


class FundTerm(str, Enum):
    FALL = "FALL"
    SPRING = "SPRING"
    SUMMER = "SUMMER"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    SCORED = "SCORED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CommitteeAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class RubricScoreStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETRACTED = "RETRACTED"


class AwardStatus(str, Enum):
    COMMITTED = "COMMITTED"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"


class RenewalReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class StewardshipStatus(str, Enum):
    DRAFT = "DRAFT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
class ScholarshipFund(TypedDict):
    id: str
    fund_name: str
    endowment_cents: int
    committed_cents: int
    disbursed_cents: int
    available_cents: int
    award_term: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityCriteria(TypedDict):
    id: str
    fund_id: str
    min_gpa: float
    required_residency_state: str
    required_field_of_study: str
    max_award_cents: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    self_reported_gpa: float
    residency_state: str
    field_of_study: str
    institution_id: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    fund_id: str
    applicant_id: str
    eligibility_matched: Optional[bool]
    eligibility_failures: Optional[List[str]]
    requested_amount_cents: int
    rubric_total: Optional[float]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable upload: id + created_at only
class Recommendation(TypedDict):
    id: str
    application_id: str
    recommender_name: str
    document_uri: str
    created_at: str


class Transcript(TypedDict):
    id: str
    application_id: str
    document_uri: str
    verified_gpa: float
    created_at: str


class CommitteeMember(TypedDict):
    id: str
    full_name: str
    email: str
    expertise_field: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class CommitteeAssignment(TypedDict):
    id: str
    application_id: str
    committee_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RubricScore(TypedDict):
    id: str
    application_id: str
    committee_member_id: str
    academic_score: int
    need_score: int
    essay_score: int
    weighted_value: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    application_id: str
    fund_id: str
    provisional_award_cents: int
    final_award_cents: Optional[int]
    renewal_gpa_floor: float
    term_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    award_id: str
    fund_id: str
    institution_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalReview(TypedDict):
    id: str
    award_id: str
    reported_gpa: float
    meets_floor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StewardshipRecord(TypedDict):
    id: str
    award_id: str
    thank_you_text: str
    status: str
    created_at: str
    updated_at: str
    version: int
