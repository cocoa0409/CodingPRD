"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RESIDENT = "Resident"
    REVIEWER = "Reviewer"
    BUDGET_ADMIN = "BudgetAdmin"


class VotingMethod(str, Enum):
    RANKED = "RANKED"
    ALLOCATION = "ALLOCATION"


class CyclePhase(str, Enum):
    DRAFT = "DRAFT"
    SUBMISSION = "SUBMISSION"
    DEVELOPMENT = "DEVELOPMENT"
    VOTING = "VOTING"
    SELECTION = "SELECTION"
    IMPLEMENTATION = "IMPLEMENTATION"
    CLOSED = "CLOSED"


class ResidentEligibility(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEVELOPING = "DEVELOPING"
    REJECTED = "REJECTED"
    COSTED = "COSTED"
    ON_BALLOT = "ON_BALLOT"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    IN_IMPLEMENTATION = "IN_IMPLEMENTATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BallotStatus(str, Enum):
    DRAFT = "DRAFT"
    CAST = "CAST"
    WITHDRAWN = "WITHDRAWN"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


# common_fields: true — id + created_at + updated_at + version
class BudgetCycle(TypedDict):
    id: str
    name: str
    fiscal_year: int
    total_budget_cents: int
    voting_method: str
    per_project_cap_cents: int
    per_voter_allocation_cap_cents: int
    min_voter_age: int
    default_language: str
    submission_start: str
    submission_end: str
    voting_start: str
    voting_end: str
    phase: str
    total_committed_cents: int
    uncommitted_cents: int
    completed_project_count: int
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict):
    id: str
    budget_cycle_id: str
    name: str
    description: str
    category_budget_cap_cents: int
    display_order: int
    committed_cents: int
    remaining_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    residency_document_ref: str
    residency_address: str
    preferred_language: str
    accessibility_needs: List[str]
    eligibility_status: str
    age: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    budget_cycle_id: str
    category_id: str
    submitter_id: str
    title: str
    summary: str
    translations: dict
    status: str
    provisional_estimate_cents: int
    estimated_cost_cents: int
    vote_score: int
    awarded_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostLineItem(TypedDict):
    id: str
    proposal_id: str
    label: str
    unit_cost_cents: int
    quantity: int
    contingency_pct: float
    line_provisional_cents: int
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict):
    id: str
    budget_cycle_id: str
    voter_id: str
    status: str
    method: str
    total_allocated_cents: int
    cast_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotEntry(TypedDict):
    id: str
    ballot_id: str
    proposal_id: str
    rank: Optional[int]
    allocated_cents: Optional[int]
    points: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class SelectionRun(TypedDict):
    id: str
    budget_cycle_id: str
    selected_count: int
    total_awarded_cents: int
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    proposal_id: str
    title: str
    scheduled_start: str
    scheduled_end: str
    status: str
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at, no version)
class ReportBack(TypedDict):
    id: str
    proposal_id: str
    period_label: str
    narrative: str
    translations: dict
    spent_cents: int
    published_at: str
    created_at: str
