"""Domain types for the Grocery Fuel Points & Cross-Banner Loyalty API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Twelve of the thirteen resource types carry the full audit triple
(``created_at``, ``updated_at``, ``version``); ``PointLedgerEntry`` is the
exception and carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    STORE_OPERATOR = "StoreOperator"
    PUMP_TERMINAL = "PumpTerminal"
    MEMBER = "Member"
    LOYALTY_ANALYST = "LoyaltyAnalyst"
    LOYALTY_SUPERVISOR = "LoyaltySupervisor"
    SETTLEMENT_CLERK = "SettlementClerk"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class BannerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ExpiryBasis(str, Enum):
    LOT_FIFO = "LOT_FIFO"
    CYCLE_SCOPED = "CYCLE_SCOPED"


class FraudScoringMode(str, Enum):
    INSTANTANEOUS = "INSTANTANEOUS"
    TRAILING_WEIGHTED = "TRAILING_WEIGHTED"


class SiteType(str, Enum):
    GROCERY = "GROCERY"
    OWNED_FUEL_CENTER = "OWNED_FUEL_CENTER"
    PARTNER_STATION = "PARTNER_STATION"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class FrozenReason(str, Enum):
    MANUAL = "MANUAL"
    AUTO_FRAUD_SCORE = "AUTO_FRAUD_SCORE"


class LinkRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class HouseholdLinkStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PromoEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PointCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class PurchaseCategory(str, Enum):
    GROCERY = "GROCERY"
    GIFT_CARD = "GIFT_CARD"
    PHARMACY = "PHARMACY"
    FUEL = "FUEL"
    TOBACCO = "TOBACCO"
    ALCOHOL = "ALCOHOL"


class PostingStatus(str, Enum):
    RECORDED = "RECORDED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class AccrualStatus(str, Enum):
    NOT_ACCRUED = "NOT_ACCRUED"
    ACCRUED = "ACCRUED"
    REVERSED = "REVERSED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"
    REDEMPTION = "REDEMPTION"
    REDEMPTION_RELEASE = "REDEMPTION_RELEASE"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    EXPIRY = "EXPIRY"
    ROLLOVER = "ROLLOVER"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerSourceKind(str, Enum):
    PURCHASE_TRANSACTION = "PURCHASE_TRANSACTION"
    FUEL_REDEMPTION = "FUEL_REDEMPTION"
    POINT_DISPUTE = "POINT_DISPUTE"
    POINT_CYCLE = "POINT_CYCLE"
    POINT_TRANSFER = "POINT_TRANSFER"


class AuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DISPENSED = "DISPENSED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class SettlementStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    BATCHED = "BATCHED"
    SETTLED = "SETTLED"


class SettlementBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisputeReasonCode(str, Enum):
    MISSING_ACCRUAL = "MISSING_ACCRUAL"
    WRONG_MULTIPLIER = "WRONG_MULTIPLIER"
    UNAUTHORIZED_REDEMPTION = "UNAUTHORIZED_REDEMPTION"
    EXPIRY_ERROR = "EXPIRY_ERROR"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    ADJUSTMENT_PROPOSED = "ADJUSTMENT_PROPOSED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DENIED = "RESOLVED_DENIED"


class AuthorityTier(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class FraudSignalType(str, Enum):
    ALT_ID_SHARING = "ALT_ID_SHARING"
    RAPID_TRANSFER = "RAPID_TRANSFER"
    CROSS_BANNER_VELOCITY = "CROSS_BANNER_VELOCITY"
    OVERDRAWN_AUTH = "OVERDRAWN_AUTH"
    GEO_IMPOSSIBLE = "GEO_IMPOSSIBLE"


class FraudSignalStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class FraudSignalSource(str, Enum):
    ANALYST = "ANALYST"
    SYSTEM = "SYSTEM"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Banner(TypedDict):
    id: str
    banner_code: str
    name: str
    status: str
    base_points_per_dollar: int
    gift_card_multiplier: int
    pharmacy_multiplier: int
    pharmacy_points_per_script: int
    max_stacked_multiplier: int
    max_stack_count: int
    points_per_discount_block: int
    cents_off_per_block: int
    max_cents_off_per_gallon: int
    owned_max_gallons_per_redemption: int
    min_points_per_redemption: int
    rollover_cap_points: int
    max_transfers_per_cycle: int
    expiry_basis: str
    fraud_scoring_mode: str
    freeze_threshold_score: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    banner_id: str
    site_number: str
    site_type: str
    status: str
    partner_code: Optional[str]
    per_gallon_cap_cents: Optional[int]
    max_gallons_per_redemption: Optional[int]
    unbatched_gallons: float
    unbatched_discount_cents: int
    settlement_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    banner_id: str
    household_code: str
    status: str
    frozen_reason: Optional[str]
    frozen_at: Optional[str]
    linked_member_count: int
    aggregate_available_points: int
    cross_banner_member_ids: List[str]
    fraud_score: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    banner_id: str
    alt_id: str
    card_number: str
    full_name: str
    available_points: int
    lifetime_points: int
    created_at: str
    updated_at: str
    version: int


class HouseholdLink(TypedDict):
    id: str
    household_id: str
    member_id: str
    link_role: str
    status: str
    is_cross_banner: bool
    activated_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromoEvent(TypedDict):
    id: str
    banner_id: str
    promo_code: str
    multiplier: int
    applies_to_categories: List[str]
    starts_at: str
    ends_at: str
    stack_priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PointCycle(TypedDict):
    id: str
    banner_id: str
    cycle_month: str
    opens_at: str
    closes_at: str
    status: str
    expired_points_total: int
    rolled_over_points_total: int
    swept_member_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseTransaction(TypedDict):
    id: str
    member_id: str
    site_id: str
    transacted_at: str
    lines: List[dict]
    subtotal_cents: int
    posting_status: str
    accrual_status: str
    gross_points_awarded: int
    line_points_breakdown: List[dict]
    applied_promo_event_ids: List[str]
    posted_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointLedgerEntry(TypedDict):
    """Append-only ledger row: carries only ``id`` and ``created_at``.

    The PRD states that ledger rows are immutable by construction, so both
    ``updated_at`` and ``version`` are absent from a ledger entry entirely.
    """

    id: str
    member_id: str
    point_cycle_id: str
    entry_type: str
    points_delta: int
    lot_expires_at: Optional[str]
    source_kind: str
    source_ref_id: str
    memo: Optional[str]
    created_at: str


class FuelRedemption(TypedDict):
    id: str
    member_id: str
    site_id: str
    settlement_batch_id: Optional[str]
    alt_id_presented: str
    points_committed: int
    blocks_effective: int
    cents_off_per_gallon: int
    points_debited_at_auth: int
    gallons_authorized: float
    gallons_dispensed: Optional[float]
    discount_amount_cents: Optional[int]
    authorization_status: str
    settlement_status: str
    authorized_at: str
    dispensed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    site_id: str
    period_start: str
    period_end: str
    status: str
    redemption_count: int
    gallons_total: float
    gross_discount_cents: int
    tier_rate_pct: float
    pre_fee_reimbursement_cents: int
    admin_fee_cents: int
    reimbursement_cents: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointDispute(TypedDict):
    id: str
    member_id: str
    disputed_ledger_entry_id: str
    supersedes_dispute_id: Optional[str]
    applied_ledger_entry_id: Optional[str]
    claimed_points: int
    reason_code: str
    status: str
    proposed_points_delta: Optional[int]
    authority_tier: Optional[str]
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudSignal(TypedDict):
    id: str
    household_id: str
    signal_type: str
    severity_weight: int
    status: str
    source: str
    detected_at: str
    cleared_at: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointsSummary(TypedDict):
    member_id: str
    available_points: int
    open_cycle_id: Optional[str]
    pending_authorized_points: int
    projected_expiring_points: int
    projected_rollover_points: int
    projected_available_after_close: int
