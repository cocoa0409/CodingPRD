"""Domain types for the streaming royalty distribution API: entity TypedDicts,
status enums and the role enum.

Every enum value and every field name below is taken from the PRD's entity
definitions and state machines.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    ROYALTY_ADMIN = "RoyaltyAdmin"
    RIGHTS_OPS_ANALYST = "RightsOpsAnalyst"
    RIGHTS_HOLDER_USER = "RightsHolderUser"
    REGULATORY_OFFICER = "RegulatoryOfficer"


# ─── Enumerated domains ───────────────────────────────

class HolderType(str, Enum):
    LABEL = "LABEL"
    DISTRIBUTOR = "DISTRIBUTOR"
    PUBLISHER = "PUBLISHER"
    COLLECTIVE = "COLLECTIVE"


class WorkType(str, Enum):
    RECORDING = "RECORDING"
    COMPOSITION = "COMPOSITION"


class RightsState(str, Enum):
    UNMATCHED = "UNMATCHED"
    PROVISIONAL = "PROVISIONAL"
    REGISTERED = "REGISTERED"
    DISPUTED = "DISPUTED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    USAGE_SEALED = "USAGE_SEALED"
    DISTRIBUTED = "DISTRIBUTED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class UsageBatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    RECONCILED = "RECONCILED"


class SubscriptionTier(str, Enum):
    FREE_AD_SUPPORTED = "FREE_AD_SUPPORTED"
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    STUDENT = "STUDENT"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    AUTO_MATCHED = "AUTO_MATCHED"
    CLAIM_MATCHED = "CLAIM_MATCHED"
    DISPUTED = "DISPUTED"


class RightType(str, Enum):
    MASTER = "MASTER"
    MECHANICAL = "MECHANICAL"
    PERFORMANCE = "PERFORMANCE"


class Routing(str, Enum):
    DIRECT = "DIRECT"
    COLLECTIVE = "COLLECTIVE"


class RegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class DenominatorBasis(str, Enum):
    ALL_USAGE = "ALL_USAGE"
    MATCHED_ONLY = "MATCHED_ONLY"


class AllocationBasis(str, Enum):
    REVENUE_SHARE = "REVENUE_SHARE"
    PER_SUBSCRIBER_MINIMUM = "PER_SUBSCRIBER_MINIMUM"
    STATUTORY_FLOOR = "STATUTORY_FLOOR"


class PoolStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"
    REOPENED_FOR_ADJUSTMENT = "REOPENED_FOR_ADJUSTMENT"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class LineType(str, Enum):
    USAGE = "USAGE"
    HOLDING_RELEASE = "HOLDING_RELEASE"
    RESIDUAL = "RESIDUAL"
    ADJUSTMENT = "ADJUSTMENT"


class ProductionStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class FindingStatus(str, Enum):
    NONE = "NONE"
    ASSERTED = "ASSERTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class RateScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class SettlementResolution(str, Enum):
    UPHOLD = "UPHOLD"
    WITHDRAW = "WITHDRAW"


# ─── Entities carrying id/created_at/updated_at/version ─────────────

class RightsHolder(TypedDict):
    id: str
    legal_name: str
    holder_type: str
    home_territory_code: str
    direct_deal_rate_bps: Optional[int]
    receivable_balance_cents: int
    issued_statement_count: int
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict):
    id: str
    work_type: str
    identifier: str
    title: str
    artist_credit: Optional[str]
    linked_work_id: Optional[str]
    normalized_title: str
    normalized_artist: Optional[str]
    rights_state: str
    approved_master_share_bps: int
    provisional_match_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountingPeriod(TypedDict):
    id: str
    label: str
    usage_start: str
    usage_end: str
    claim_window_closes_at: str
    status: str
    total_holding_cents: int
    created_at: str
    updated_at: str
    version: int


class UsageBatch(TypedDict):
    id: str
    period_id: str
    source_label: str
    status: str
    line_count: int
    total_play_count: int
    matched_play_count: int
    unmatched_play_count: int
    disputed_play_count: int
    created_at: str
    updated_at: str
    version: int


class UsageLine(TypedDict):
    id: str
    batch_id: str
    work_id: Optional[str]
    reported_isrc: Optional[str]
    reported_title: str
    reported_artist: Optional[str]
    territory_code: str
    subscription_tier: str
    play_count: int
    match_status: str
    match_confidence_bps: int
    attributed_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class RightsRegistration(TypedDict):
    id: str
    work_id: str
    claimant_id: str
    collective_id: Optional[str]
    right_type: str
    routing: str
    share_bps: int
    territory_set: List[str]
    effective_from: str
    effective_to: str
    supersede_overlapping: bool
    payee_holder_id: str
    status: str
    evidence_round: int
    reviewed_by_user_id: Optional[str]
    disputing_holder_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyPool(TypedDict):
    id: str
    period_id: str
    territory_code: str
    subscription_tier: str
    subscriber_count: int
    gross_revenue_cents: int
    applied_rate_schedule_id: Optional[str]
    revenue_share_pool_cents: int
    minimum_pool_cents: int
    statutory_floor_cents: int
    total_play_count: int
    denominator_basis: Optional[str]
    denominator_play_count: int
    distributable_cents: int
    allocation_basis: Optional[str]
    matched_attributed_cents: int
    holding_cents: int
    rounding_residual_cents: int
    residual_payee_holder_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    rights_holder_id: str
    period_id: str
    status: str
    gross_cents: int
    admin_fee_cents: int
    net_payable_cents: int
    line_count: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict):
    id: str
    rights_holder_id: str
    statement_id: str
    requested_scope_start: str
    requested_scope_end: str
    production_deadline_at: str
    required_line_count: int
    produced_line_count: int
    production_status: str
    finding_status: str
    asserted_underpayment_cents: int
    settled_amount_cents: int
    interest_cents: int
    finding_note: Optional[str]
    findings_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict):
    id: str
    proceeding_ref: str
    territory_code: str
    subscription_tier: str
    revenue_share_bps: int
    per_subscriber_minimum_cents: int
    mechanical_share_bps: int
    performance_share_bps: int
    statutory_floor_per_play_millicents: int
    effective_from: str
    effective_to: str
    retroactive: bool
    status: str
    promulgated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity: carries ONLY id + created_at ───────────────
# A statement line is immutable once written, so it has no updated_at and no
# version field at all.

class StatementLine(TypedDict):
    id: str
    statement_id: str
    pool_id: Optional[str]
    work_id: Optional[str]
    adjustment_of_line_id: Optional[str]
    payee_holder_id: str
    line_type: str
    right_type: Optional[str]
    routing: Optional[str]
    territory_code: Optional[str]
    subscription_tier: Optional[str]
    play_count: int
    share_bps: int
    gross_cents: int
    admin_fee_cents: int
    net_cents: int
    created_at: str
