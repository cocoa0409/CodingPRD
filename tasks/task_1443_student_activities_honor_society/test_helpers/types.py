"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the standard system-managed properties of PRD section 2.5
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ACTIVITIES_DIRECTOR = "ActivitiesDirector"
    ADVISOR = "Advisor"
    OFFICER = "Officer"
    MEMBER = "Member"


class ChapterStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class ChapterStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATIONARY = "PROBATIONARY"
    REVOKED = "REVOKED"


class MemberStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    ON_PROBATION = "ON_PROBATION"
    DISMISSED = "DISMISSED"
    ALUMNUS = "ALUMNUS"


class CycleStatus(str, Enum):
    PLANNED = "PLANNED"
    NOMINATION = "NOMINATION"
    REVIEW = "REVIEW"
    INDUCTED = "INDUCTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Semester(str, Enum):
    FALL = "FALL"
    SPRING = "SPRING"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INDUCTED = "INDUCTED"
    WITHDRAWN = "WITHDRAWN"


class ServiceHourStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    TALLIED = "TALLIED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class Office(str, Enum):
    PRESIDENT = "PRESIDENT"
    VICE_PRESIDENT = "VICE_PRESIDENT"
    SECRETARY = "SECRETARY"
    TREASURER = "TREASURER"
    HISTORIAN = "HISTORIAN"


class VoteStatus(str, Enum):
    CAST = "CAST"
    VOIDED = "VOIDED"


class OfficerRoleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


class MinutesStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    AMENDED = "AMENDED"


class FundraiserStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADVISOR_APPROVED = "ADVISOR_APPROVED"
    DIRECTOR_APPROVED = "DIRECTOR_APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    FUNDRAISER_DEPOSIT = "FUNDRAISER_DEPOSIT"
    UPFRONT_COST_DISBURSEMENT = "UPFRONT_COST_DISBURSEMENT"
    DUES_REMITTANCE = "DUES_REMITTANCE"
    NATIONAL_DUES_PAYMENT = "NATIONAL_DUES_PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerEntryStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class DuesPaymentStatus(str, Enum):
    PENDING_REMITTANCE = "PENDING_REMITTANCE"
    REMITTED = "REMITTED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class ProbationCaseStatus(str, Enum):
    OPEN = "OPEN"
    APPEALED = "APPEALED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ProbationOutcome(str, Enum):
    CONFIRMED = "STANDARDS_VIOLATION_CONFIRMED"
    NOT_CONFIRMED = "STANDARDS_VIOLATION_NOT_CONFIRMED"


class ReasonCode(str, Enum):
    GPA_BELOW_THRESHOLD = "GPA_BELOW_THRESHOLD"
    SERVICE_HOURS_SHORTFALL = "SERVICE_HOURS_SHORTFALL"
    CONDUCT_VIOLATION = "CONDUCT_VIOLATION"
    MISSED_MEETINGS = "MISSED_MEETINGS"


class AthleticsPriority(str, Enum):
    PRACTICE = "PRACTICE"
    GAME = "GAME"
    TOURNAMENT = "TOURNAMENT"


class AthleticsBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class Chapter(TypedDict, total=False):
    id: str
    school_name: str
    charter_number: str
    advisor_user_id: str
    gpa_threshold_weighted: float
    gpa_threshold_unweighted: float
    service_hours_annual_required: int
    service_hours_per_semester_required: int
    national_dues_cents_per_member: int
    status: str
    standing: str
    current_cycle_id: Optional[str]
    fund_balance_cents: int
    dues_arrears_cents: int
    active_member_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    chapter_id: str
    student_id: str
    full_name: str
    email: str
    grade_level: int
    weighted_gpa: float
    unweighted_gpa: float
    status: str
    inducted_cycle_id: Optional[str]
    verified_service_hours_current_year: float
    verified_service_hours_current_semester: float
    probation_strikes: int
    is_officer: bool
    good_standing: bool
    created_at: str
    updated_at: str
    version: int


class MembershipCycle(TypedDict, total=False):
    id: str
    chapter_id: str
    cycle_label: str
    academic_year: str
    semester: str
    nomination_open_date: str
    nomination_close_date: str
    induction_date: str
    status: str
    candidate_member_ids: List[str]
    inducted_count: int
    created_at: str
    updated_at: str
    version: int


class CycleApplication(TypedDict, total=False):
    id: str
    chapter_id: str
    cycle_id: str
    member_id: str
    nominated_by_user_id: str
    status: str
    eligibility_score: float
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceHourEntry(TypedDict, total=False):
    id: str
    chapter_id: str
    member_id: str
    activity_name: str
    service_date: str
    hours: float
    organization: str
    supervisor_email: str
    status: str
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OfficerElection(TypedDict, total=False):
    id: str
    chapter_id: str
    cycle_id: str
    office: str
    status: str
    opened_at: Optional[str]
    tallied_at: Optional[str]
    winner_member_id: Optional[str]
    runoff_required: bool
    created_at: str
    updated_at: str
    version: int


class ElectionVote(TypedDict, total=False):
    id: str
    chapter_id: str
    election_id: str
    voter_member_id: str
    candidate_member_id: str
    cast_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficerRole(TypedDict, total=False):
    id: str
    chapter_id: str
    election_id: str
    member_id: str
    office: str
    status: str
    started_at: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeetingMinutes(TypedDict, total=False):
    id: str
    chapter_id: str
    meeting_date: str
    called_by_officer_id: str
    attendees_member_ids: List[str]
    agenda: str
    notes: str
    status: str
    submitted_by_officer_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundraiserRequest(TypedDict, total=False):
    id: str
    chapter_id: str
    title: str
    description: str
    goal_amount_cents: int
    upfront_cost_cents: int
    requested_by_officer_id: str
    scheduled_date: str
    status: str
    actual_gross_cents: Optional[int]
    actual_net_cents: Optional[int]
    advisor_approved_by_user_id: Optional[str]
    director_approved_by_user_id: Optional[str]
    segregation_of_duties_enforced: bool
    created_at: str
    updated_at: str
    version: int


class FundLedgerEntry(TypedDict, total=False):
    id: str
    chapter_id: str
    fundraiser_id: Optional[str]
    entry_type: str
    amount_cents: int
    entry_date: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesPayment(TypedDict, total=False):
    id: str
    chapter_id: str
    member_id: str
    academic_year: str
    amount_cents: int
    paid_at: str
    status: str
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProbationCase(TypedDict, total=False):
    id: str
    chapter_id: str
    member_id: str
    opened_by_user_id: str
    reason_code: str
    evidence_text: str
    opened_at: str
    status: str
    outcome: Optional[str]
    probation_end_date: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AthleticsCalendarBlock(TypedDict, total=False):
    id: str
    chapter_id: str
    member_id: str
    block_start: str
    block_end: str
    sport: str
    priority: str
    status: str
    created_at: str
    updated_at: str
    version: int
