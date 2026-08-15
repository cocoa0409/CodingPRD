"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    GOVERNANCE_ADMIN = "GovernanceAdmin"
    BOARD_CHAIR = "BoardChair"
    BOARD_DIRECTOR = "BoardDirector"
    TREASURER = "Treasurer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    EXECUTIVE_DIRECTOR = "ExecutiveDirector"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class BylawsStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    DEFEATED = "DEFEATED"
    WITHDRAWN = "WITHDRAWN"


class MemberStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    PAST = "PAST"
    TERM_LIMITED_OUT = "TERM_LIMITED_OUT"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


class OfficerRole(str, Enum):
    NONE = "NONE"
    CHAIR = "CHAIR"
    TREASURER = "TREASURER"
    SECRETARY = "SECRETARY"


class TermStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    VACATED = "VACATED"


class CommitteeStatus(str, Enum):
    CHARTERED = "CHARTERED"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    DISSOLVED = "DISSOLVED"


class CommitteeType(str, Enum):
    AUDIT = "AUDIT"
    FINANCE = "FINANCE"
    GOVERNANCE = "GOVERNANCE"
    NOMINATING = "NOMINATING"
    EXECUTIVE = "EXECUTIVE"
    COMPENSATION = "COMPENSATION"
    OTHER = "OTHER"


class AppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class EndedReason(str, Enum):
    MANUAL = "MANUAL"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"
    COI_RESTRICTION = "COI_RESTRICTION"
    COMMITTEE_DISSOLVED = "COMMITTEE_DISSOLVED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    MINUTES_DRAFTED = "MINUTES_DRAFTED"
    MINUTES_APPROVED = "MINUTES_APPROVED"
    CANCELLED = "CANCELLED"


class MotionStatus(str, Enum):
    INTRODUCED = "INTRODUCED"
    VOTING_OPEN = "VOTING_OPEN"
    TABLED = "TABLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class MotionCategory(str, Enum):
    GOVERNANCE = "GOVERNANCE"
    FINANCE = "FINANCE"
    PERSONNEL = "PERSONNEL"
    POLICY = "POLICY"
    BYLAWS = "BYLAWS"
    FUNDRAISING = "FUNDRAISING"
    OTHER = "OTHER"


class VoteChoice(str, Enum):
    AYE = "AYE"
    NAY = "NAY"
    ABSTAIN = "ABSTAIN"
    RECUSED = "RECUSED"


class DisclosureStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    RESTRICTIONS_IMPOSED = "RESTRICTIONS_IMPOSED"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    RATIFIED = "RATIFIED"
    DELIVERED = "DELIVERED"


class Rating(str, Enum):
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVATED = "ACTIVATED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_BOARD_REVIEW = "IN_BOARD_REVIEW"
    APPROVED = "APPROVED"
    FILED = "FILED"
    PUBLIC_DISCLOSED = "PUBLIC_DISCLOSED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RENEWAL_DUE = "RENEWAL_DUE"
    RENEWAL_SUBMITTED = "RENEWAL_SUBMITTED"
    LAPSED = "LAPSED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


SKILL_TAGS = [
    "FINANCE", "LEGAL", "FUNDRAISING", "PROGRAM",
    "GOVERNANCE", "MARKETING", "TECHNOLOGY", "HR",
]


class Nonprofit(TypedDict, total=False):
    id: str
    name: str
    ein: str
    state_of_incorporation: str
    fiscal_year_end_month: int
    annual_gross_receipts_cents: int
    current_fiscal_year: int
    compliance_posture: str
    adopted_policies: list
    created_at: str
    updated_at: str
    version: int


class Bylaws(TypedDict, total=False):
    id: str
    nonprofit_id: str
    version_no: int
    quorum_pct: int
    quorum_basis: str
    amendment_threshold_pct: int
    term_length_years: int
    max_consecutive_terms: int
    term_cooloff_years: int
    board_size: int
    status: str
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BylawsAmendment(TypedDict, total=False):
    id: str
    nonprofit_id: str
    base_bylaws_id: str
    title: str
    proposed_fields: dict
    motion_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardMember(TypedDict, total=False):
    id: str
    nonprofit_id: str
    full_name: str
    email: str
    skill_tags: list
    officer_role: str
    is_independent: bool
    status: str
    consecutive_terms_served: int
    has_active_restrictions: bool
    created_at: str
    updated_at: str
    version: int


class BoardTerm(TypedDict, total=False):
    id: str
    nonprofit_id: str
    board_member_id: str
    bylaws_id: str
    start_date: str
    end_date: str
    chain_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict, total=False):
    id: str
    nonprofit_id: str
    name: str
    type: str
    min_members: int
    authorized_size: int
    requires_all_independent: bool
    active_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeAppointment(TypedDict, total=False):
    id: str
    nonprofit_id: str
    committee_id: str
    board_member_id: str
    committee_role: str
    status: str
    ended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict, total=False):
    id: str
    nonprofit_id: str
    committee_id: Optional[str]
    scheduled_start: str
    duration_minutes: int
    notice_sent_at: Optional[str]
    notice_waived: bool
    status: str
    attendance: list
    quorum_base: Optional[int]
    quorum_required: Optional[int]
    quorum_met: Optional[bool]
    minutes_text: Optional[str]
    minutes_recorded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Motion(TypedDict, total=False):
    id: str
    nonprofit_id: str
    meeting_id: str
    bylaws_amendment_id: Optional[str]
    policy_title: Optional[str]
    title: str
    category: str
    threshold: str
    threshold_basis: str
    votes_for: int
    votes_against: int
    votes_abstain: int
    votes_recused: int
    required_votes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): carries only id + created_at; no updated_at, no version.
class Vote(TypedDict, total=False):
    id: str
    nonprofit_id: str
    motion_id: str
    board_member_id: str
    choice: str
    created_at: str


class COIDisclosure(TypedDict, total=False):
    id: str
    nonprofit_id: str
    board_member_id: str
    fiscal_year: int
    answers: list
    has_conflict: bool
    status: str
    reviewer_member_id: Optional[str]
    restriction_categories: list
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class ExecutiveEvaluation(TypedDict, total=False):
    id: str
    nonprofit_id: str
    fiscal_year: int
    executive_name: str
    scores: list
    provisional_composite: Optional[float]
    final_composite: Optional[float]
    rating: Optional[str]
    recorded_by_user_id: Optional[str]
    ratified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SuccessionPlan(TypedDict, total=False):
    id: str
    nonprofit_id: str
    target_role: str
    readiness: str
    interim_designee_member_id: Optional[str]
    interim_designee_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Form990Filing(TypedDict, total=False):
    id: str
    nonprofit_id: str
    fiscal_year: int
    supersedes_filing_id: Optional[str]
    total_revenue_cents: int
    total_expenses_cents: int
    contributions_cents: int
    program_service_revenue_cents: int
    net_change_cents: int
    public_support_ratio: float
    preparer_user_id: str
    approved_by_user_id: Optional[str]
    reviewed_by_member_ids: list
    review_required_count: Optional[int]
    filing_due_date: str
    filed_on: Optional[str]
    filed_late: Optional[bool]
    public_disclosure_posted_at: Optional[str]
    disclosure_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict, total=False):
    id: str
    nonprofit_id: str
    state_code: str
    renewal_cycle_months: int
    current_period_end: str
    contributions_in_state_cents: Optional[int]
    renewal_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    nonprofit_id: str
    prior_policy_id: Optional[str]
    policy_type: str
    carrier: str
    coverage_limit_cents: int
    premium_cents: int
    policy_start_date: str
    policy_end_date: str
    acknowledge_gap: bool
    gap_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
