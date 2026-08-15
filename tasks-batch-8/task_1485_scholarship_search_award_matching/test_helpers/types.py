"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STUDENT = "Student"
    COORDINATOR = "ScholarshipCoordinator"
    REVIEWER = "CommitteeReviewer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    DONOR = "Donor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SELECTED = "SELECTED"
    WAITLISTED = "WAITLISTED"
    NOT_SELECTED = "NOT_SELECTED"
    AWARDED = "AWARDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ComponentStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"


class ReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    SUPPRESSED = "SUPPRESSED"


class ReviewCycleStatus(str, Enum):
    SETUP = "SETUP"
    SCORING = "SCORING"
    DELIBERATION = "DELIBERATION"
    FINALIZED = "FINALIZED"


class ReviewScoreStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class AwardOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AwardFundingStatus(str, Enum):
    NONE = "NONE"
    ENCUMBERED = "ENCUMBERED"
    DISBURSING = "DISBURSING"
    FULLY_DISBURSED = "FULLY_DISBURSED"
    OVER_DISBURSED = "OVER_DISBURSED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class AdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class RenewalStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED_ELIGIBLE = "VERIFIED_ELIGIBLE"
    VERIFIED_INELIGIBLE = "VERIFIED_INELIGIBLE"
    APPEALED = "APPEALED"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"


class ThankYouLetterStatus(str, Enum):
    REQUIRED = "REQUIRED"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    WAIVED = "WAIVED"


class DonorReportStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ProgramType(str, Enum):
    MERIT = "MERIT"
    NEED = "NEED"
    HYBRID = "HYBRID"


class MatchPolicy(str, Enum):
    STRICT = "STRICT"
    HOLISTIC = "HOLISTIC"


class StackingScope(str, Enum):
    ANNUAL = "ANNUAL"
    PER_TERM = "PER_TERM"


class IntendedMajor(str, Enum):
    STEM = "STEM"
    ARTS = "ARTS"
    BUSINESS = "BUSINESS"
    HEALTH = "HEALTH"
    TRADES = "TRADES"
    UNDECIDED = "UNDECIDED"


class ComponentType(str, Enum):
    ESSAY = "ESSAY"
    RECOMMENDATION = "RECOMMENDATION"
    TRANSCRIPT = "TRANSCRIPT"


class AdjustmentReason(str, Enum):
    OVER_AWARD = "OVER_AWARD"
    DUPLICATE = "DUPLICATE"
    DATA_ERROR = "DATA_ERROR"
    WITHDRAWAL = "WITHDRAWAL"


class ReportFrequency(str, Enum):
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    grade_level: int
    gpa_hundredths: int
    verified_gpa_hundredths: Optional[int]
    residency_state: str
    intended_major: str
    household_income_cents: int
    efc_cents: int
    cost_of_attendance_cents: int
    institution_name: str
    tags: List[str]
    status: str
    total_accepted_cents: int
    total_disbursed_cents: int
    aid_cap_cents: int
    excess_cents: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    anonymous: bool
    report_frequency: str
    created_at: str
    updated_at: str
    version: int


class AwardFund(TypedDict, total=False):
    id: str
    name: str
    committed_cents: int
    reserved_cents: int
    disbursed_cents: int
    returned_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class ScholarshipProgram(TypedDict, total=False):
    id: str
    name: str
    donor_id: str
    fund_id: str
    program_type: str
    match_policy: str
    stacking_scope: str
    award_amount_cents: int
    max_recipients: int
    min_gpa_hundredths: int
    eligible_majors: List[str]
    required_residency_state: Optional[str]
    max_household_income_cents: Optional[int]
    required_tags: List[str]
    required_components: List[str]
    application_open_at: str
    application_close_at: str
    renewable: bool
    renewal_min_gpa_hundredths: Optional[int]
    renewal_min_credits: Optional[int]
    max_renewals: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    student_id: str
    program_id: str
    status: str
    provisional_match_score: Optional[float]
    verified_match_score: Optional[float]
    submitted_at: Optional[str]
    returned_count: int
    cycle_score: Optional[float]
    decision_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ApplicationComponent(TypedDict, total=False):
    id: str
    application_id: str
    component_type: str
    required: bool
    status: str
    content_ref: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict, total=False):
    id: str
    application_id: str
    offset_code: str
    send_at: str
    status: str
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewCycle(TypedDict, total=False):
    id: str
    program_id: str
    label: str
    starts_on: str
    ends_on: str
    quorum_count: int
    selection_quota: int
    waitlist_quota: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewScore(TypedDict, total=False):
    id: str
    cycle_id: str
    application_id: str
    reviewer_user_id: str
    academic_score: int
    essay_score: int
    need_score: int
    conflict_of_interest: bool
    status: str
    weighted_total: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    application_id: str
    student_id: str
    amount_cents: int
    offer_status: str
    funding_status: str
    offer_expires_at: str
    accepted_at: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    award_id: str
    term_seq: int
    amount_cents: int
    scheduled_date: str
    term_start_date: str
    term_end_date: str
    institution_name: str
    status: str
    sent_by_user_id: Optional[str]
    sent_at: Optional[str]
    confirmed_at: Optional[str]
    returned_at: Optional[str]
    returned_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardAdjustment(TypedDict, total=False):
    id: str
    award_id: str
    reason: str
    delta_cents: int
    status: str
    auto_generated: bool
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalEvaluation(TypedDict, total=False):
    id: str
    award_id: str
    term_label: str
    reported_gpa_hundredths: int
    reported_credits: int
    registrar_gpa_hundredths: Optional[int]
    registrar_credits: Optional[int]
    status: str
    verified_by_user_id: Optional[str]
    decided_at: Optional[str]
    appeal_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ThankYouLetter(TypedDict, total=False):
    id: str
    award_id: str
    status: str
    content_ref: Optional[str]
    auto_created: bool
    due_at: str
    created_at: str
    updated_at: str
    version: int


class DonorReport(TypedDict, total=False):
    id: str
    donor_id: str
    period_start: str
    period_end: str
    status: str
    total_awards_count: Optional[int]
    total_disbursed_cents: Optional[int]
    thank_you_complete: Optional[bool]
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
