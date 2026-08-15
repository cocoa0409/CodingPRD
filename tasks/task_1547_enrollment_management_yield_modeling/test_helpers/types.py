"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the common system fields id/created_at/updated_at/version
per the PRD's common resource properties section.
"""
from enum import Enum
from typing import Optional, TypedDict


class CycleStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    REVIEW_CLOSED = "REVIEW_CLOSED"
    DECISIONS_RELEASED = "DECISIONS_RELEASED"
    ENROLLMENT_TRACKING = "ENROLLMENT_TRACKING"
    CLOSED = "CLOSED"


class IntakePosture(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class ApplicantType(str, Enum):
    FIRST_YEAR = "FIRST_YEAR"
    TRANSFER = "TRANSFER"
    READMIT = "READMIT"


class InquirySource(str, Enum):
    WEB_FORM = "WEB_FORM"
    CAMPUS_VISIT = "CAMPUS_VISIT"
    COLLEGE_FAIR = "COLLEGE_FAIR"
    REFERRAL = "REFERRAL"
    PURCHASED_LIST = "PURCHASED_LIST"


class DistanceBand(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"
    INTERNATIONAL = "INTERNATIONAL"


class PriorStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    ACADEMIC_PROBATION = "ACADEMIC_PROBATION"
    DISMISSED = "DISMISSED"


class FunnelStage(str, Enum):
    INQUIRY = "INQUIRY"
    APPLIED = "APPLIED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    WAITLISTED = "WAITLISTED"
    DEPOSITED = "DEPOSITED"
    ENROLLED = "ENROLLED"
    MELTED = "MELTED"
    WITHDRAWN = "WITHDRAWN"


class ReviewStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class Recommendation(str, Enum):
    ADMIT = "ADMIT"
    DENY = "DENY"
    WAITLIST = "WAITLIST"


class FundType(str, Enum):
    MERIT = "MERIT"
    NEED_BASED = "NEED_BASED"


class AidOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class DepositStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class WaitlistEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACTIVATED = "ACTIVATED"
    EXPIRED = "EXPIRED"
    REMOVED = "REMOVED"


class InterventionType(str, Enum):
    OUTREACH_CALL = "OUTREACH_CALL"
    ADVISOR_MEETING = "ADVISOR_MEETING"
    EMAIL_CAMPAIGN = "EMAIL_CAMPAIGN"


class InterventionOutcome(str, Enum):
    REACHED_ENGAGED = "REACHED_ENGAGED"
    REACHED_CONFIRMED = "REACHED_CONFIRMED"
    NO_CONTACT = "NO_CONTACT"


class TriggerSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_THRESHOLD = "AUTO_THRESHOLD"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    ENROLLMENT_MANAGER = "EnrollmentManager"
    ADMISSIONS_OFFICER = "AdmissionsOfficer"
    APPLICATION_READER = "ApplicationReader"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    APPLICANT = "Applicant"


class AdmissionCycle(TypedDict, total=False):
    id: str
    name: str
    application_opens_at: str
    application_deadline_at: str
    deposit_deadline_at: str
    census_at: str
    target_class_size: int
    status: str
    inquiry_count: int
    application_count: int
    admitted_count: int
    deposited_count: int
    enrolled_count: int
    decisioned_count: int
    admit_rate: float
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    cycle_id: str
    name: str
    capacity_seats: int
    target_enrollment: int
    tuition_cents: int
    scholarship_budget_cents: int
    deposit_amount_cents: int
    auto_waitlist_activation: bool
    admitted_count: int
    deposited_count: int
    enrolled_count: int
    seats_open: int
    scholarship_committed_cents: int
    scholarship_available_cents: int
    intake_posture: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    cycle_id: str
    full_name: str
    email: str
    applicant_type: str
    inquiry_source: str
    distance_band: str
    transfer_credit_hours: int
    prior_standing: str
    funnel_stage: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    program_id: str
    cycle_id: str
    academic_score: float
    efc_cents: int
    submitted_at: str
    review_round: int
    submitted_read_count: int
    aid_accepted_cents: int
    aid_gap_cents: int
    melt_risk_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeReview(TypedDict, total=False):
    id: str
    application_id: str
    reader_id: str
    window_start_at: str
    window_end_at: str
    score_academic: float
    score_fit: float
    recommendation: str
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AidOffer(TypedDict, total=False):
    id: str
    application_id: str
    fund_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    application_id: str
    amount_cents: int
    paid_at: str
    refund_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    application_id: str
    program_id: str
    rank_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MeltIntervention(TypedDict, total=False):
    id: str
    application_id: str
    advisor_id: str
    intervention_type: str
    window_start_at: str
    window_end_at: str
    trigger_source: str
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int
