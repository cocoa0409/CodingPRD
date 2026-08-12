"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    LR_ADMIN = "LRAdmin"
    LR_MANAGER = "LRManager"
    NEGOTIATOR = "Negotiator"
    CHIEF_NEGOTIATOR = "ChiefNegotiator"
    UNION_REPRESENTATIVE = "UnionRepresentative"
    LEGAL_COUNSEL = "LegalCounsel"


class UnionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUSTEED = "TRUSTEED"
    DECERTIFIED = "DECERTIFIED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXTENDED = "EXTENDED"
    REPLACED = "REPLACED"
    ARCHIVED = "ARCHIVED"


class AgreementPosture(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    OPEN = "OPEN"
    SUNSET = "SUNSET"
    CRITICAL = "CRITICAL"
    UNCOVERED = "UNCOVERED"
    CLOSED = "CLOSED"


class DeadlineMode(str, Enum):
    BUSINESS = "BUSINESS"
    CALENDAR = "CALENDAR"


class ClauseInterpretationStatus(str, Enum):
    UNINTERPRETED = "UNINTERPRETED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INTERPRETED = "INTERPRETED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ProposalSide(str, Enum):
    EMPLOYER = "EMPLOYER"
    UNION = "UNION"


class ProposalType(str, Enum):
    ECONOMIC = "ECONOMIC"
    NON_ECONOMIC = "NON_ECONOMIC"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    ON_TABLE = "ON_TABLE"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    IMPLEMENTED = "IMPLEMENTED"
    VOID = "VOID"


class ScenarioMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    REVIEWED = "REVIEWED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class VoteStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"


class LetterType(str, Enum):
    SIDE_LETTER = "SIDE_LETTER"
    MOA = "MOA"
    MOU = "MOU"


class SideLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_LEGAL = "PENDING_LEGAL"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PracticeStatus(str, Enum):
    ASSERTED = "ASSERTED"
    DOCUMENTED = "DOCUMENTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    ABANDONED = "ABANDONED"


class InfoRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    OBJECTED = "OBJECTED"


class TaskType(str, Enum):
    NOTICE_DEADLINE = "NOTICE_DEADLINE"
    DATA_PREP = "DATA_PREP"
    SUNSET_COMMUNICATION = "SUNSET_COMMUNICATION"
    STRIKE_CONTINGENCY = "STRIKE_CONTINGENCY"
    BUDGET_REOPENER = "BUDGET_REOPENER"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    MISSED = "MISSED"


# All entities in this PRD carry the standard common-field set:
# id, created_at, updated_at, version (PRD §2.10).


class Union(TypedDict, total=False):
    id: str
    name: str
    union_code: str
    status: str
    open_information_request_count: int
    created_at: str
    updated_at: str
    version: int


class CollectiveAgreement(TypedDict, total=False):
    id: str
    union_id: str
    title: str
    effective_date: str
    expiration_date: str
    headcount_baseline: int
    fte_projected: int
    avg_loaded_wage_cents: int
    costing_envelope_cents: int
    envelope_committed_cents: int
    deadline_mode: str
    status: str
    posture: str
    extension_count: int
    created_at: str
    updated_at: str
    version: int


class Clause(TypedDict, total=False):
    id: str
    agreement_id: str
    article_ref: str
    title: str
    body_text: str
    is_economic: bool
    interpretation_status: str
    interpretation_text: Optional[str]
    resolved_by_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BargainingSession(TypedDict, total=False):
    id: str
    agreement_id: str
    mediator_id: str
    lead_negotiator_id: str
    location: str
    start_at: str
    end_at: str
    status: str
    summary_note: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    agreement_id: str
    clause_id: Optional[str]
    side: str
    title: str
    proposal_type: str
    wage_increase_pct: Optional[float]
    affected_headcount: Optional[int]
    includes_benefits: bool
    one_time_cost_cents: int
    recurring_annual_cost_cents: int
    session_id: Optional[str]
    round_number: int
    status: str
    submitted_by_user_id: str
    supersedes_proposal_id: Optional[str]
    estimated_year1_cost_cents: Optional[int]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostingScenario(TypedDict, total=False):
    id: str
    agreement_id: str
    name: str
    scenario_mode: str
    term_years: int
    proposal_ids: List[str]
    status: str
    computed_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    locked_by_user_id: Optional[str]
    year_breakdown_cents: List[int]
    subtotal_cents: int
    reserve_cents: int
    total_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class RatificationVote(TypedDict, total=False):
    id: str
    agreement_id: str
    eligible_voter_count: int
    ballot_close_at: str
    status: str
    opened_by_user_id: Optional[str]
    votes_for: Optional[int]
    votes_against: Optional[int]
    votes_cast: Optional[int]
    quorum_met: Optional[bool]
    retro_payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SideLetter(TypedDict, total=False):
    id: str
    agreement_id: str
    clause_id: str
    letter_type: str
    title: str
    effective_start: str
    effective_end: str
    status: str
    drafted_by_user_id: str
    executed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PastPractice(TypedDict, total=False):
    id: str
    union_id: str
    clause_id: Optional[str]
    title: str
    description: str
    first_observed_date: str
    last_observed_date: str
    occurrence_count: int
    status: str
    strength_legalistic: Optional[float]
    strength_operational: Optional[float]
    asserted_by_user_id: str
    abandon_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InformationRequest(TypedDict, total=False):
    id: str
    union_id: str
    agreement_id: Optional[str]
    subject: str
    received_at: str
    status: str
    due_at: str
    is_overdue: bool
    extension_count: int
    response_note: Optional[str]
    objection_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpirationTask(TypedDict, total=False):
    id: str
    agreement_id: str
    title: str
    task_type: str
    due_offset_days: int
    due_date: str
    assignee_user_id: str
    status: str
    completed_late: bool
    created_at: str
    updated_at: str
    version: int
