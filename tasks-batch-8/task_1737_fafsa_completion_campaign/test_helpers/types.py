"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CAMPAIGN_ADMIN = "CampaignAdmin"
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    STAFF_MEMBER = "StaffMember"
    SPECIALIST = "Specialist"
    MATCH_REVIEWER = "MatchReviewer"
    DATA_IMPORTER = "DataImporter"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    STATE_GRACE = "STATE_GRACE"
    CLOSED = "CLOSED"


class SchoolStatus(str, Enum):
    INVITED = "INVITED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class RecognitionTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    UNRATED = "UNRATED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERLOADED = "OVERLOADED"
    SUSPENDED = "SUSPENDED"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class Capability(str, Enum):
    EVENT_STAFF = "EVENT_STAFF"
    AID_EXPERT = "AID_EXPERT"
    CASE_SPECIALIST = "CASE_SPECIALIST"


class DependencyStatus(str, Enum):
    DEPENDENT = "DEPENDENT"
    INDEPENDENT = "INDEPENDENT"
    PENDING_REVIEW = "PENDING_REVIEW"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    SUGGESTED = "SUGGESTED"
    MATCHED = "MATCHED"


class FafsaStatus(str, Enum):
    NO_RECORD = "NO_RECORD"
    STARTED = "STARTED"
    SUBMITTED = "SUBMITTED"
    VERIFICATION_SELECTED = "VERIFICATION_SELECTED"
    COMPLETE = "COMPLETE"


class DeadlineClassification(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    ON_TRACK_STATE = "ON_TRACK_STATE"
    STATE_MISSED_FEDERAL_OPEN = "STATE_MISSED_FEDERAL_OPEN"
    LATE = "LATE"


class DataVisibility(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"


class AidRecordStatus(str, Enum):
    STARTED = "STARTED"
    SUBMITTED = "SUBMITTED"
    VERIFICATION_SELECTED = "VERIFICATION_SELECTED"
    COMPLETE = "COMPLETE"


class MatchLinkStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    AUTO_REJECTED = "AUTO_REJECTED"
    INVALIDATED = "INVALIDATED"


class ConsentScope(str, Enum):
    STATUS_DETAIL = "STATUS_DETAIL"
    OUTREACH = "OUTREACH"
    DATA_SHARE = "DATA_SHARE"


class GrantedBy(str, Enum):
    PARENT = "PARENT"
    ADULT_STUDENT = "ADULT_STUDENT"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentRole(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    EXPERT = "EXPERT"


class AssignmentStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"


class ChecklistTemplate(str, Enum):
    DEPENDENT_STANDARD = "DEPENDENT_STANDARD"
    INDEPENDENT_STANDARD = "INDEPENDENT_STANDARD"


class ChecklistStatus(str, Enum):
    GENERATED = "GENERATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ARCHIVED = "ARCHIVED"


class DocType(str, Enum):
    STUDENT_ID = "STUDENT_ID"
    STUDENT_TAX_RETURN = "STUDENT_TAX_RETURN"
    PARENT_TAX_RETURN = "PARENT_TAX_RETURN"
    BANK_STATEMENT = "BANK_STATEMENT"
    DEPENDENCY_OVERRIDE_FORM = "DEPENDENCY_OVERRIDE_FORM"


class ChecklistItemStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"


class CaseType(str, Enum):
    VERIFICATION_FOLLOWUP = "VERIFICATION_FOLLOWUP"
    SPECIAL_CIRCUMSTANCE = "SPECIAL_CIRCUMSTANCE"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_FAMILY = "AWAITING_FAMILY"
    ESCALATED = "ESCALATED"
    PAUSED = "PAUSED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ResolutionOutcome(str, Enum):
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    INDEPENDENT_CONFIRMED = "INDEPENDENT_CONFIRMED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class ReportVariant(str, Enum):
    SUBMISSION_BASED = "SUBMISSION_BASED"
    PROCESSED_BASED = "PROCESSED_BASED"


class ReportStatus(str, Enum):
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; §3 entity payloads)
# AidStatusEvent is the single append-only exception: id + created_at only.
# ---------------------------------------------------------------------------
class Campaign(TypedDict, total=False):
    id: str
    name: str
    academic_year: str
    state_grant_deadline: str
    federal_deadline: str
    total_budget_cents: int
    auto_confirm_threshold: float
    review_floor: float
    min_subgroup_size: int
    max_caseload: int
    no_show_limit: int
    min_recognition_seniors: int
    status: str
    committed_budget_cents: int
    spent_budget_cents: int
    budget_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    campaign_id: str
    name: str
    district_code: str
    school_code: str
    status: str
    recognition_tier: str
    created_at: str
    updated_at: str
    version: int


class StaffProfile(TypedDict, total=False):
    id: str
    campaign_id: str
    full_name: str
    capabilities: List[str]
    languages: List[str]
    background_check_status: str
    status: str
    confirmed_hours_total: float
    no_show_count: int
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class SeniorRecord(TypedDict, total=False):
    id: str
    school_id: str
    student_ref: str
    full_name: str
    dob: str
    home_language: str
    subgroup_tags: List[str]
    efc_band: str
    dependency_status: str
    match_status: str
    fafsa_status: Optional[str]
    submitted_at: Optional[str]
    deadline_classification: Optional[str]
    current_match_link_id: Optional[str]
    data_visibility: str
    created_at: str
    updated_at: str
    version: int


class AidRecord(TypedDict, total=False):
    id: str
    campaign_id: str
    external_ref: str
    full_name: str
    dob: str
    school_code: str
    district_code: str
    current_status: str
    last_effective_date: str
    created_at: str
    updated_at: str
    version: int


class AidStatusEvent(TypedDict, total=False):
    # Append-only log entry: carries id and created_at ONLY (PRD §2.4).
    id: str
    created_at: str
    aid_record_id: str
    fafsa_status: str
    effective_date: str
    source: str


class ScoreComponents(TypedDict, total=False):
    dob_exact: bool
    name_exact: bool
    school_code_match: bool
    district_match: bool


class MatchLink(TypedDict, total=False):
    id: str
    senior_record_id: str
    aid_record_id: str
    match_score: float
    score_components: ScoreComponents
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    senior_record_id: str
    scopes: List[str]
    granted_by: str
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffingCoverageBlock(TypedDict, total=False):
    expert_ratio: float
    staff_count: int
    language_complete: bool


class StaffingCoverage(TypedDict, total=False):
    committed: StaffingCoverageBlock
    pipeline: StaffingCoverageBlock


class CompletionEvent(TypedDict, total=False):
    id: str
    school_id: str
    title: str
    start_time: str
    end_time: str
    capacity: int
    cost_estimate_cents: int
    actual_cost_cents: Optional[int]
    required_expert_count: int
    supported_languages: List[str]
    status: str
    staffing_coverage: StaffingCoverage
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict, total=False):
    id: str
    event_id: str
    staff_profile_id: str
    assigned_role: str
    status: str
    duration_hours: float
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    senior_record_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentChecklist(TypedDict, total=False):
    id: str
    senior_record_id: str
    language: str
    template_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChecklistItem(TypedDict, total=False):
    id: str
    checklist_id: str
    doc_type: str
    status: str
    waivable: bool
    created_at: str
    updated_at: str
    version: int


class SupportCase(TypedDict, total=False):
    id: str
    senior_record_id: str
    assigned_specialist_id: Optional[str]
    case_type: str
    status: str
    previous_status: Optional[str]
    resolution_outcome: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class ReportRow(TypedDict, total=False):
    dimension: str
    key: str
    eligible_count: int
    completed_count: int
    state_deadline_met_count: int
    rate: float


class CompletionReport(TypedDict, total=False):
    id: str
    campaign_id: str
    variant: str
    status: str
    rows: List[ReportRow]
    eligible_count: int
    completed_count: int
    overall_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int
