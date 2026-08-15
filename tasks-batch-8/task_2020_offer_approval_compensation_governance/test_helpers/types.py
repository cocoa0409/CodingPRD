"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    HIRING_MANAGER = "HiringManager"
    RECRUITER = "Recruiter"
    COMP_ANALYST = "CompAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    DEPARTMENT_DIRECTOR = "DepartmentDirector"
    VP_PEOPLE = "VPPeople"
    BACKGROUND_SCREENER = "BackgroundScreener"
    CANDIDATE = "Candidate"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    BUDGET_REVIEW = "BUDGET_REVIEW"
    RANGE_APPROVAL = "RANGE_APPROVAL"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CandidateStatus(str, Enum):
    PROSPECT = "PROSPECT"
    IN_PROCESS = "IN_PROCESS"
    HIRED = "HIRED"
    ARCHIVED = "ARCHIVED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    LETTER_GENERATED = "LETTER_GENERATED"
    EXTENDED = "EXTENDED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    HIRED = "HIRED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"
    WITHDRAWN = "WITHDRAWN"


class ApprovalStepStatus(str, Enum):
    WAITING = "WAITING"
    ACTIONABLE = "ACTIONABLE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class NegotiationRoundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PerkStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ClearanceCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class OfferLetterStatus(str, Enum):
    GENERATED = "GENERATED"
    SUPERSEDED = "SUPERSEDED"


class DelegationGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Requisition(TypedDict, total=False):
    id: str
    title: str
    department: str
    role_level: str
    geo_tier: str
    hiring_manager_id: str
    annual_budget_cents: int
    salary_min_cents: int
    salary_mid_cents: int
    salary_max_cents: int
    headcount_authorized: int
    headcount_filled: int
    committed_budget_cents: int
    status: str
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    current_base_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InternalEquitySnapshot(TypedDict, total=False):
    id: str
    role_level: str
    geo_tier: str
    base_cents: int
    bonus_target_pct: float
    created_at: str
    updated_at: str
    version: int


class ApprovalPolicy(TypedDict, total=False):
    id: str
    min_band_severity: str
    required_role: str
    chain_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    requisition_id: str
    candidate_id: str
    created_by_user_id: str
    base_cents: int
    bonus_target_pct: float
    equity_shares: int
    equity_fmv_cents: int
    band: str
    bonus_target_cents: int
    total_cash_cents: int
    cash_only_annual_cost_cents: int
    fully_loaded_annual_cost_cents: int
    equity_compa_ratio: Optional[float]
    equity_percentile: Optional[int]
    equity_compa_risk_flag: bool
    equity_percentile_risk_flag: bool
    clearance_posture: str
    round_count: int
    original_submitted_base_cents: Optional[int]
    expires_at: Optional[str]
    status: str
    declination_reason: Optional[str]
    rescind_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalStep(TypedDict, total=False):
    id: str
    offer_id: str
    sequence: int
    required_role: str
    status: str
    decided_by_user_id: Optional[str]
    decided_via_delegation: bool
    delegation_grant_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict, total=False):
    id: str
    offer_id: str
    sequence: int
    proposed_base_cents: int
    proposed_bonus_target_pct: Optional[float]
    proposed_equity_shares: Optional[int]
    concession_pct: float
    status: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerkPackage(TypedDict, total=False):
    id: str
    offer_id: str
    kind: str
    amount_cents: int
    clawback_months: int
    clawback_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClearanceCheck(TypedDict, total=False):
    id: str
    offer_id: str
    kind: str
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OfferLetter(TypedDict, total=False):
    id: str
    offer_id: str
    sequence: int
    pinned_offer_version: int
    body_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfferEvent(TypedDict, total=False):
    # Append-only resource: carries id + created_at only (no updated_at, no version)
    id: str
    offer_id: str
    sequence: int
    event_type: str
    actor_user_id: str
    detail: Optional[str]
    created_at: str


class DelegationGrant(TypedDict, total=False):
    id: str
    grantor_user_id: str
    delegate_user_id: str
    scope_role: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int
