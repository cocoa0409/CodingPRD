"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry id/created_at/updated_at/version except BidRevision,
which is an append-only audit record carrying only id + created_at from the
common set (PRD section 2.4).
"""
from enum import Enum
from typing import Optional, TypedDict


class BidPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    TABULATED = "TABULATED"
    RECOMMENDATION_PENDING = "RECOMMENDATION_PENDING"
    AWARDED = "AWARDED"


class PrequalStatus(str, Enum):
    """Subcontractor.current_prequal_status derived values."""
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PrequalApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class InvitationStatus(str, Enum):
    SENT = "SENT"
    BIDDING = "BIDDING"
    DECLINED = "DECLINED"


class AcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WAIVED = "WAIVED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class DisqualificationReason(str, Enum):
    MISSING_ADDENDUM_ACK = "MISSING_ADDENDUM_ACK"
    PREQUAL_LAPSED = "PREQUAL_LAPSED"


class LevelingTreatment(str, Enum):
    GC_ALLOWANCE = "GC_ALLOWANCE"
    SUB_QUOTE = "SUB_QUOTE"
    EXCLUDED_SCOPE = "EXCLUDED_SCOPE"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class RecommendationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class FeedbackStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"


class UserRole(str, Enum):
    LEAD_ESTIMATOR = "LeadEstimator"
    CHIEF_ESTIMATOR = "ChiefEstimator"
    PREQUAL_REVIEWER = "PrequalReviewer"
    SUBCONTRACTOR = "Subcontractor"
    ANONYMOUS = "Anonymous"


# --- Entity TypedDicts (total=False: nullable/read-side fields vary) ---

class BidPackage(TypedDict, total=False):
    id: str
    name: str
    trade_code: str
    bid_due_at: str
    bid_bond_required_pct: float
    status: str
    issued_addendum_count: int
    submitted_bid_count: int
    compliant_bid_count: Optional[int]
    apparent_low_bid_id: Optional[str]
    leveled_low_bid_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    license_number: str
    current_prequal_status: str
    created_at: str
    updated_at: str
    version: int


class PrequalApplication(TypedDict, total=False):
    id: str
    subcontractor_id: str
    declared_annual_revenue_cents: int
    declared_emr: float
    declared_bonding_capacity_cents: int
    self_reported_score: float
    verified_annual_revenue_cents: Optional[int]
    verified_emr: Optional[float]
    verified_bonding_capacity_cents: Optional[int]
    verified_score: Optional[float]
    review_notes: Optional[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict, total=False):
    id: str
    bid_package_id: str
    subcontractor_id: str
    status: str
    responded_at: Optional[str]
    first_plan_room_access_at: Optional[str]
    plan_room_access_count: int
    created_at: str
    updated_at: str
    version: int


class Addendum(TypedDict, total=False):
    id: str
    bid_package_id: str
    number: int
    summary: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class AddendumAcknowledgment(TypedDict, total=False):
    id: str
    addendum_id: str
    subcontractor_id: str
    status: str
    acknowledged_at: Optional[str]
    waived_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    bid_package_id: str
    subcontractor_id: str
    base_bid_cents: int
    bond_amount_cents: int
    submitted_at: str
    addendum_ack_complete: bool
    disqualification_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BidRevision(TypedDict, total=False):
    # Append-only audit row: id + created_at only, NO updated_at / version.
    id: str
    created_at: str
    bid_id: str
    sequence: int
    amount_cents: int
    note: Optional[str]
    is_last_minute: bool
    revised_at: str


class LevelingAdjustment(TypedDict, total=False):
    id: str
    bid_id: str
    description: str
    treatment: str
    amount_cents: Optional[int]
    pct_of_base: Optional[float]
    resolved_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PostBidInterview(TypedDict, total=False):
    id: str
    bid_id: str
    interview_room: str
    scheduled_start: str
    scheduled_end: str
    outcome_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardRecommendation(TypedDict, total=False):
    id: str
    bid_package_id: str
    recommended_bid_id: str
    rationale: str
    created_by_user_id: str
    decision_notes: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BidderFeedback(TypedDict, total=False):
    id: str
    bid_id: str
    leveled_rank: int
    leveled_amount_cents: int
    winning_leveled_amount_cents: int
    notes: Optional[str]
    sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
