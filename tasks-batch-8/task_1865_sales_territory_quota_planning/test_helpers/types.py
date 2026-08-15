"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API carries the four system-managed properties
(id, created_at, updated_at, version) per PRD common-properties rules.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SALES_OPS_ADMIN = "SalesOpsAdmin"
    SALES_OPS_ANALYST = "SalesOpsAnalyst"
    REV_OPS_MANAGER = "RevOpsManager"
    SALES_REP = "SalesRep"


class PlanYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUBMISSIONS_CLOSED = "SUBMISSIONS_CLOSED"
    RECONCILED = "RECONCILED"
    COMMUNICATED = "COMMUNICATED"
    LOCKED = "LOCKED"


class TerritoryStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssignmentRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RuleType(str, Enum):
    NAMED_ACCOUNT = "NAMED_ACCOUNT"
    GEO_SEGMENT = "GEO_SEGMENT"


class Segment(str, Enum):
    ENTERPRISE = "ENTERPRISE"
    MID_MARKET = "MID_MARKET"
    SMB = "SMB"


class AssignmentSource(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    NAMED_RULE = "NAMED_RULE"
    GEO_RULE = "GEO_RULE"
    MANUAL_CHANGE = "MANUAL_CHANGE"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"


class RepAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    LOCKED_IN = "LOCKED_IN"


class ReconciliationStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"


class ReconciliationPolicy(str, Enum):
    TOP_DOWN_WINS = "TOP_DOWN_WINS"
    BLENDED = "BLENDED"


class CreditTransitionPolicy(str, Enum):
    PRORATE_BY_DAY = "PRORATE_BY_DAY"
    MONTH_SNAPSHOT = "MONTH_SNAPSHOT"


class ChangeRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CreditEventType(str, Enum):
    BOOKING = "BOOKING"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"


class CreditEventStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERRULED = "RESOLVED_OVERRULED"
    WITHDRAWN = "WITHDRAWN"


class CoverageStatus(str, Enum):
    NO_QUOTA = "NO_QUOTA"
    GAP = "GAP"
    UNDERSTAFFED = "UNDERSTAFFED"
    COVERED = "COVERED"


class PlanYear(TypedDict):
    id: str
    label: str
    start_date: str
    end_date: str
    company_target_cents: int
    productivity_per_rep_cents: int
    reconciliation_policy: str
    credit_transition_policy: str
    lock_date: str
    status: str
    communicated_at: Optional[str]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    plan_year_id: str
    parent_territory_id: Optional[str]
    name: str
    potential_cents: int
    headcount_capacity: int
    assigned_quota_cents: Optional[int]
    final_quota_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentRule(TypedDict):
    id: str
    plan_year_id: str
    rule_type: str
    priority: int
    country_code: Optional[str]
    state_code: Optional[str]
    segment: Optional[str]
    named_account_id: Optional[str]
    territory_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    plan_year_id: str
    name: str
    country_code: str
    state_code: Optional[str]
    segment: str
    annual_potential_cents: int
    assigned_territory_id: Optional[str]
    assignment_source: str
    assignment_rule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesRep(TypedDict):
    id: str
    full_name: str
    email: str
    hire_date: str
    created_at: str
    updated_at: str
    version: int


class RampSchedule(TypedDict):
    id: str
    name: str
    multipliers: List[float]
    created_at: str
    updated_at: str
    version: int


class RepAssignment(TypedDict):
    id: str
    plan_year_id: str
    rep_id: str
    territory_id: str
    ramp_schedule_id: Optional[str]
    effective_from: str
    effective_to: Optional[str]
    status: str
    base_quota_cents: Optional[int]
    ramped_quota_cents: Optional[int]
    final_quota_cents: Optional[int]
    attainment_cents: int
    attainment_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AllocationResultRow(TypedDict):
    territory_id: str
    allocated_cents: int


class TopDownAllocation(TypedDict):
    id: str
    plan_year_id: str
    scope_territory_id: str
    pool_cents: int
    status: str
    results: Optional[List[AllocationResultRow]]
    created_at: str
    updated_at: str
    version: int


class BottomUpSubmission(TypedDict):
    id: str
    plan_year_id: str
    territory_id: str
    submitted_by_rep_id: str
    proposed_quota_cents: int
    rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationResultRow(TypedDict):
    territory_id: str
    top_down_cents: int
    bottom_up_cents: Optional[int]
    deviation_pct: Optional[float]
    final_cents: int
    escalated: bool


class ReconciliationRun(TypedDict):
    id: str
    plan_year_id: str
    policy_used: str
    results: List[ReconciliationResultRow]
    status: str
    created_at: str
    updated_at: str
    version: int


class TerritoryChangeRequest(TypedDict):
    id: str
    plan_year_id: str
    account_id: str
    from_territory_id: str
    to_territory_id: str
    effective_date: str
    reason: Optional[str]
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    quota_transfer_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditEvent(TypedDict):
    id: str
    plan_year_id: str
    account_id: str
    rep_id: str
    event_type: str
    amount_cents: int
    booking_date: str
    source_change_request_id: Optional[str]
    parent_credit_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnershipDispute(TypedDict):
    id: str
    plan_year_id: str
    account_id: str
    claimant_territory_id: str
    filed_by_rep_id: str
    reason: str
    filed_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
