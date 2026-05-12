"""Domain types for the Garbage Sorting Points API.

Entity TypedDicts mirror PRD §3 and the 'Common Resource Properties' section.
Entities with common fields carry id, created_at, updated_at, version.
PointsTransaction and AuditLog are append-only and carry only id + created_at.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_OPERATOR = "SystemOperator"
    COMMUNITY_ADMIN = "CommunityAdmin"
    APPEAL_REVIEWER = "AppealReviewer"
    RESIDENT = "Resident"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CommunityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class IdentityStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AccountStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class ResidentRelation(str, Enum):
    HEAD = "HEAD"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    OTHER = "OTHER"


class GarbageCategory(str, Enum):
    RECYCLABLE = "RECYCLABLE"
    HAZARDOUS = "HAZARDOUS"
    KITCHEN = "KITCHEN"
    OTHER = "OTHER"


class ScoringMethod(str, Enum):
    MANUAL = "MANUAL"
    AI = "AI"
    SCALE = "SCALE"


class PointRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DisposalStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class PointsTxnKind(str, Enum):
    DISPOSAL_CREDIT = "DISPOSAL_CREDIT"
    REDEMPTION_DEBIT = "REDEMPTION_DEBIT"
    REDEMPTION_REFUND = "REDEMPTION_REFUND"
    VIOLATION_DEBIT = "VIOLATION_DEBIT"
    VIOLATION_REVERSAL = "VIOLATION_REVERSAL"
    MISJUDGMENT_ADJUSTMENT = "MISJUDGMENT_ADJUSTMENT"


class RelatedEntityKind(str, Enum):
    DISPOSAL = "DISPOSAL"
    REDEMPTION_ORDER = "REDEMPTION_ORDER"
    VIOLATION = "VIOLATION"


class MallItemStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class MallChannel(str, Enum):
    ONLINE = "ONLINE"
    STATION = "STATION"


class RedemptionOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class ViolationType(str, Enum):
    MIS_SORTING = "MIS_SORTING"
    LITTERING = "LITTERING"
    NO_CLASSIFICATION = "NO_CLASSIFICATION"


class ViolationStatus(str, Enum):
    NEW = "NEW"
    APPEALED = "APPEALED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class RankingGranularity(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class RankingDimension(str, Enum):
    HOUSEHOLD = "HOUSEHOLD"
    BUILDING = "BUILDING"
    COMMUNITY = "COMMUNITY"


class RankingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PUBLISHED = "PUBLISHED"


class AppealDecision(str, Enum):
    UPHOLD = "UPHOLD"
    OVERTURN = "OVERTURN"


class VerifyDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AuditAction(str, Enum):
    POINTS_ADJUSTMENT = "POINTS_ADJUSTMENT"
    VIOLATION_RECORDED = "VIOLATION_RECORDED"
    VIOLATION_APPEAL_DECISION = "VIOLATION_APPEAL_DECISION"
    RULE_PUBLISHED = "RULE_PUBLISHED"
    RANKING_PUBLISHED = "RANKING_PUBLISHED"


class AuditSubjectKind(str, Enum):
    DISPOSAL = "DISPOSAL"
    VIOLATION = "VIOLATION"
    POINT_RULE = "POINT_RULE"
    RANKING_PERIOD = "RANKING_PERIOD"
    HOUSEHOLD = "HOUSEHOLD"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common-fields entities carry id+created_at+updated_at+version
# Append-only entities (PointsTransaction, AuditLog) carry only id+created_at.
# ---------------------------------------------------------------------------
class Community(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    code: str
    timezone: str
    status: str


class Household(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    address: str
    building_code: str
    head_resident_id: Optional[str]
    points_balance: int
    lifetime_points_earned: int
    status: str


class Resident(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    full_name: str
    id_document_hash: str
    relation: str
    identity_status: str
    account_status: str
    restricted_until: Optional[str]
    consecutive_disposal_days: int


class PointRule(TypedDict, total=False):
    id: str
    created_at: str
    community_id: str
    category: str
    version: int
    base_rate_per_kg: float
    bonus_consecutive_threshold_days: int
    bonus_consecutive_multiplier: float
    peak_period_start_hour: int
    peak_period_end_hour: int
    peak_period_bonus_flat: int
    category_bonus_flat: int
    daily_cap_points: int
    status: str
    activated_at: Optional[str]
    retired_at: Optional[str]


class Disposal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    resident_id: str
    community_id: str
    disposal_time: str
    location_code: str
    declared_category: str
    actual_category: str
    scoring_method: str
    accuracy_score: float
    weight_kg: Optional[float]
    volume_liters: Optional[float]
    evidence_uri: str
    applied_rule_id: str
    awarded_points: int
    cap_overflow_points: int
    status: str


# Append-only — NO updated_at, NO version
class PointsTransaction(TypedDict, total=False):
    id: str
    created_at: str
    household_id: str
    kind: str
    amount: int
    balance_after: int
    related_entity_kind: str
    related_entity_id: str


class MallItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    name: str
    cost_points: int
    stock: int
    channel: str
    status: str


class RedemptionOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    resident_id: str
    mall_item_id: str
    quantity: int
    unit_cost_points: int
    total_cost_points: int
    channel: str
    status: str
    confirmed_at: Optional[str]
    delivered_at: Optional[str]


class Violation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    resident_id: str
    household_id: str
    community_id: str
    violation_type: str
    occurred_at: str
    evidence_uri: str
    base_deduction_points: int
    repeat_count_in_window: int
    escalation_multiplier: float
    final_deduction_points: int
    status: str
    appeal_filed_at: Optional[str]
    appeal_deadline_at: str
    appeal_round: int


class RankingLeaderboardEntry(TypedDict, total=False):
    subject_id: str
    subject_kind: str
    score: int
    rank: int


class RankingPeriod(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    granularity: str
    dimension: str
    window_start: str
    window_end: str
    status: str
    published_at: Optional[str]
    leaderboard: List[RankingLeaderboardEntry]


# Append-only — NO updated_at, NO version
class AuditLog(TypedDict, total=False):
    id: str
    created_at: str
    actor_role: str
    actor_id: str
    action: str
    subject_kind: str
    subject_id: str
    before: dict
    after: dict
    reason: Optional[str]


__all__ = [
    "UserRole",
    "CommunityStatus",
    "HouseholdStatus",
    "IdentityStatus",
    "AccountStatus",
    "ResidentRelation",
    "GarbageCategory",
    "ScoringMethod",
    "PointRuleStatus",
    "DisposalStatus",
    "PointsTxnKind",
    "RelatedEntityKind",
    "MallItemStatus",
    "MallChannel",
    "RedemptionOrderStatus",
    "ViolationType",
    "ViolationStatus",
    "RankingGranularity",
    "RankingDimension",
    "RankingPeriodStatus",
    "AppealDecision",
    "VerifyDecision",
    "AuditAction",
    "AuditSubjectKind",
    "Community",
    "Household",
    "Resident",
    "PointRule",
    "Disposal",
    "PointsTransaction",
    "MallItem",
    "RedemptionOrder",
    "Violation",
    "RankingLeaderboardEntry",
    "RankingPeriod",
    "AuditLog",
]
