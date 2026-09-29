"""Typed shapes for every resource and enumeration the PRD defines.

Every persisted resource carries `id`, `created_at`, `updated_at` and `version`,
so those four properties appear on every resource TypedDict below.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER = "Seller"
    TRUSTEE = "Trustee"
    TITLE_OFFICER = "TitleOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUCTION_OPS = "AuctionOps"
    BIDDER = "Bidder"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SellerType(str, Enum):
    SERVICER = "SERVICER"
    BANK = "BANK"
    PRIVATE_SELLER = "PRIVATE_SELLER"
    GSE = "GSE"


class OccupancyStatus(str, Enum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    TENANT_OCCUPIED = "TENANT_OCCUPIED"
    VACANT = "VACANT"
    UNKNOWN = "UNKNOWN"


class TitleCondition(str, Enum):
    CLEAR = "CLEAR"
    JUNIOR_LIENS = "JUNIOR_LIENS"
    CLOUDED = "CLOUDED"
    UNKNOWN = "UNKNOWN"


class EvictionRiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ListingStatus(str, Enum):
    INTAKE = "INTAKE"
    DISCLOSURE_READY = "DISCLOSURE_READY"
    LISTED = "LISTED"
    SOLD_PENDING_CONTRACT = "SOLD_PENDING_CONTRACT"
    SOLD_CLOSED = "SOLD_CLOSED"
    UNSOLD = "UNSOLD"
    RELIST_PENDING = "RELIST_PENDING"


class TitleClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CLOUDED_DISCLOSED = "CLOUDED_DISCLOSED"
    DEFECTIVE = "DEFECTIVE"


class TrusteeSaleStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class LotStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    EXTENDED = "EXTENDED"
    SUSPENDED = "SUSPENDED"
    CLOSED_SOLD = "CLOSED_SOLD"
    CLOSED_NO_SALE = "CLOSED_NO_SALE"
    WITHDRAWN = "WITHDRAWN"


class IdentityVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RegistrationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    BARRED = "BARRED"


class ExclusionType(str, Enum):
    SANCTIONS_LIST = "SANCTIONS_LIST"
    TRUSTEE_AFFILIATE = "TRUSTEE_AFFILIATE"
    STATE_INELIGIBLE = "STATE_INELIGIBLE"
    PRIOR_FALLOUT = "PRIOR_FALLOUT"


class ExclusionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class HoldStatus(str, Enum):
    HELD = "HELD"
    EXTENDED = "EXTENDED"
    RELEASED = "RELEASED"
    CAPTURED = "CAPTURED"


class ReleasedReason(str, Enum):
    OUTBID = "OUTBID"
    NO_SALE = "NO_SALE"
    CONTRACT_CLOSED = "CONTRACT_CLOSED"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    EXTENSION_LIMIT = "EXTENSION_LIMIT"
    FORFEITED = "FORFEITED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNING = "WINNING"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"
    FALLOUT = "FALLOUT"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOID = "VOID"


class OfferStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ClearanceOutcome(str, Enum):
    CLEARED = "CLEARED"
    CLOUDED_DISCLOSED = "CLOUDED_DISCLOSED"
    DEFECTIVE = "DEFECTIVE"


class IdentityDecision(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OfferDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class AssessmentMode(str, Enum):
    SCREEN = "SCREEN"
    AUDIT = "AUDIT"


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class Seller(CommonFields):
    org_name: str
    seller_type: str
    contact_email: str
    settlement_account_ref: str
    default_commission_bps: int
    settled_net_cents: int


class AssetListing(CommonFields):
    seller_id: str
    street_address: str
    city: str
    county_code: str
    state_code: str
    estimated_value_cents: int
    occupancy_status: str
    title_condition: str
    eviction_risk_tier: str
    listing_status: str
    title_clearance_status: str
    relist_count: int
    second_chance_eligible: bool
    disclosure_ack_at: Optional[str]


class TrusteeSale(CommonFields):
    asset_listing_id: str
    county_code: str
    sale_scheduled_at: str
    statutory_max_postponements: int
    postponement_count: int
    status: str
    confirmation_reference: Optional[str]
    cancellation_reason: Optional[str]


class AuctionEvent(CommonFields):
    title: str
    county_code: str
    trustee_sale_id: Optional[str]
    starts_at: str
    ends_at: str
    event_status: str
    reschedule_count: int
    opened_at: Optional[str]
    lot_count: int


class AuctionLot(CommonFields):
    auction_event_id: str
    asset_listing_id: str
    lot_number: int
    lot_window_start_at: str
    lot_window_end_at: str
    opening_bid_cents: int
    min_increment_cents: int
    reserve_price_cents: int
    required_deposit_cents: int
    bid_close_at: str
    extension_count: int
    current_high_bid_cents: int
    hammer_price_cents: int
    provisional_buyer_premium_cents: int
    lot_status: str
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]


class Bidder(CommonFields):
    legal_name: str
    email: str
    mailing_address: str
    identity_verification_status: str
    identity_verified_at: Optional[str]
    registration_status: str
    deposit_funded_cents: int
    deposit_available_cents: int
    deposit_forfeited_cents: int
    fallout_count: int
    screen_risk_score: int


class EligibilityExclusion(CommonFields):
    bidder_id: str
    exclusion_type: str
    county_code: str
    effective_at: str
    status: str
    lifted_at: Optional[str]
    notes: Optional[str]


class DepositHold(CommonFields):
    bidder_id: str
    auction_lot_id: str
    amount_cents: int
    status: str
    expires_at: str
    extension_count: int
    released_reason: Optional[str]


class Bid(CommonFields):
    auction_lot_id: str
    bidder_id: str
    amount_cents: int
    placed_at: str
    bid_status: str
    is_above_reserve: bool
    triggered_extension: bool


class SaleContract(CommonFields):
    auction_lot_id: str
    winning_bidder_id: str
    contract_price_cents: int
    final_buyer_premium_cents: int
    doc_fee_cents: int
    total_due_cents: int
    closing_window_days: int
    closing_deadline_at: str
    contract_status: str
    execution_at: str
    executed_by_user_id: str
    settlement_status: str
    settlement_gross_cents: int
    seller_net_cents: int
    platform_fee_cents: int
    buyer_premium_cents: int
    forfeited_deposit_cents: int
    forfeiture_seller_net_cents: int
    forfeiture_platform_fee_cents: int
    fallout_reason: Optional[str]
    closing_reference: Optional[str]
    closed_at: Optional[str]
    fallout_at: Optional[str]


class SecondChanceOffer(CommonFields):
    auction_lot_id: str
    offered_bidder_id: str
    offer_price_cents: int
    expires_at: str
    status: str
    responded_at: Optional[str]


# ---------------------------------------------------------------------------
# Computed projections
# ---------------------------------------------------------------------------


class SettlementPreview(TypedDict):
    auction_lot_id: str
    hammer_price_cents: int
    contract_price_cents: int
    provisional_premium_cents: int
    final_premium_cents: int
    premium_variant_delta_cents: int
    doc_fee_cents: int
    total_due_cents: int
    settlement_gross_cents: int
    seller_net_cents: int
    platform_fee_cents: int


class EligibilityAssessment(TypedDict):
    bidder_id: str
    mode: str
    risk_score: int
    eligible: bool
    counted_exclusion_count: int
    identity_penalty_applied: int
    exclusion_penalty_applied: int
    fallout_penalty_applied: int
    deposit_penalty_applied: int
