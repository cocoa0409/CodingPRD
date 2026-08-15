"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    RIGHTS_MANAGER = "RightsManager"
    BID_COORDINATOR = "BidCoordinator"
    FINANCE_CONTROLLER = "FinanceController"
    PRODUCTION_AUDITOR = "ProductionAuditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class RightsAssetStatus(str, Enum):
    OPEN = "OPEN"
    PACKAGES_LOCKED = "PACKAGES_LOCKED"
    AWARD_CLOSED = "AWARD_CLOSED"
    RETIRED = "RETIRED"


class BroadcasterStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"
    BARRED = "BARRED"


class CreditRating(str, Enum):
    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    SPECULATIVE = "SPECULATIVE"
    UNRATED = "UNRATED"


class PlatformClass(str, Enum):
    LINEAR_TV = "LINEAR_TV"
    SVOD = "SVOD"
    AVOD = "AVOD"
    MOBILE = "MOBILE"
    RADIO = "RADIO"
    SOCIAL_CLIP = "SOCIAL_CLIP"


class RightsPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_BIDS = "OPEN_FOR_BIDS"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    AWARDED = "AWARDED"
    WITHDRAWN = "WITHDRAWN"


class ExclusivityClass(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    CO_EXCLUSIVE = "CO_EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SHORTLISTED = "SHORTLISTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ExclusivityRequest(str, Enum):
    MATCH_PACKAGE = "MATCH_PACKAGE"
    NARROWER = "NARROWER"
    BROADER = "BROADER"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    RENEWAL_OPEN = "RENEWAL_OPEN"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"
    TERMINATED_BREACH = "TERMINATED_BREACH"
    TERMINATED_CONVENIENCE = "TERMINATED_CONVENIENCE"


class DealPosture(str, Enum):
    CLEAN = "CLEAN"
    WARNING = "WARNING"
    FROZEN = "FROZEN"


class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CURED = "CURED"
    DEFAULTED = "DEFAULTED"


class ObligationStatus(str, Enum):
    TRACKING = "TRACKING"
    MET = "MET"
    SHORTFALL_DECLARED = "SHORTFALL_DECLARED"
    REMEDIED = "REMEDIED"
    CREDITED = "CREDITED"


class BroadcastEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED_BY_LEAGUE = "CANCELLED_BY_LEAGUE"
    CANCELLED_BY_BROADCASTER = "CANCELLED_BY_BROADCASTER"
    NO_SHOW = "NO_SHOW"


class MeasurementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    EXCLUDED = "EXCLUDED"


class MeasurementSource(str, Enum):
    PANEL = "PANEL"
    CENSUS = "CENSUS"
    HYBRID = "HYBRID"


class SublicenseStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class RenewalOfferStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    SUPERSEDED = "SUPERSEDED"
    EXERCISED = "EXERCISED"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class OfferSource(str, Enum):
    INCUMBENT_BROADCASTER = "INCUMBENT_BROADCASTER"
    THIRD_PARTY_BIDDER = "THIRD_PARTY_BIDDER"


class ConflictType(str, Enum):
    EXCLUSIVITY_OVERLAP = "EXCLUSIVITY_OVERLAP"
    BLACKOUT_VIOLATION = "BLACKOUT_VIOLATION"
    TERRITORY_COLLISION = "TERRITORY_COLLISION"
    PLATFORM_COLLISION = "PLATFORM_COLLISION"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---


class RightsAsset(TypedDict, total=False):
    id: str
    asset_code: str
    competition_name: str
    season_label: str
    season_start_date: str
    season_end_date: str
    total_package_pool: int
    guaranteed_rating_basis_points: int
    status: str
    active_package_count: int
    created_at: str
    updated_at: str
    version: int


class Broadcaster(TypedDict, total=False):
    id: str
    legal_name: str
    home_territory: str
    platform_classes: List[str]
    credit_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RightsPackage(TypedDict, total=False):
    id: str
    asset_id: str
    package_code: str
    territory_code: str
    platform_class: str
    window_start: str
    window_end: str
    exclusivity_class: str
    minimum_bid_cents: int
    games_committed: int
    status: str
    awarded_bid_id: Optional[str]
    awarded_deal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    package_id: str
    bidder_id: str
    round_number: int
    offered_fee_cents: int
    upfront_pct: float
    escalator_rate_pct: float
    minimum_growth_pct: float
    fee_cap_cents: int
    production_commitment_games: int
    audience_commitment_pct: float
    exclusivity_request: str
    parent_bid_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict, total=False):
    id: str
    asset_id: str
    package_id: str
    winning_bid_id: str
    broadcaster_id: str
    executed_at: Optional[str]
    term_start: str
    term_end: str
    base_fee_cents: int
    escalator_rate_pct: float
    minimum_growth_pct: float
    fee_cap_cents: int
    total_contracted_fee_cents: int
    audience_commitment_basis_points: int
    cumulative_rating_basis_points: int
    accrued_shortfall_liability_cents: int
    accrued_make_good_credit_cents: int
    payment_delinquency_count: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentMilestone(TypedDict, total=False):
    id: str
    deal_id: str
    season_index: int
    sequence_in_season: int
    due_date: str
    base_amount_cents: int
    milestone_weight: float
    escalated_amount_cents: int
    late_fee_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionObligation(TypedDict, total=False):
    id: str
    deal_id: str
    season_index: int
    games_required: int
    games_delivered: int
    shortfall_games: int
    make_good_credit_cents: int
    credit_settled_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BroadcastEvent(TypedDict, total=False):
    id: str
    deal_id: str
    obligation_id: str
    event_code: str
    scheduled_kickoff_utc: str
    actual_air_start_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AudienceMeasurement(TypedDict, total=False):
    id: str
    deal_id: str
    broadcast_event_id: str
    reporting_period_end: str
    rating_basis_points: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SublicenseRequest(TypedDict, total=False):
    id: str
    deal_id: str
    sublicensee_name: str
    sublicensee_territory: str
    sublicensee_platform_class: str
    requested_window_start: str
    requested_window_end: str
    proposed_fee_cents: int
    league_share_pct: float
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict, total=False):
    id: str
    asset_id: str
    territory_code: str
    platform_class: str
    blackout_start: str
    blackout_end: str
    applies_to_sublicense_only: bool
    reason: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict, total=False):
    id: str
    deal_id: str
    offer_source: str
    offeror_broadcaster_id: str
    offered_fee_cents: int
    escalator_rate_pct: float
    matching_window_end: str
    matched_by_incumbent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only monitor log: per PRD §2.5 a RightsConflict row carries only
# id and created_at; updated_at and version are absent.
class RightsConflict(TypedDict, total=False):
    id: str
    asset_id: str
    conflict_type: str
    left_entity_kind: str
    left_entity_id: str
    right_entity_kind: str
    right_entity_id: str
    detected_at: str
    detail: str
    created_at: str
