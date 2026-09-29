"""Domain types for the Airline Loyalty Partner & Co-Brand Program Economics API.

Role enum, every status/mode enum the PRD declares, and one TypedDict per
collection.  Eleven collections carry the four common system fields (``id``,
``created_at``, ``updated_at``, ``version``); ``MileTransaction`` and
``DeferredRevenuePosting`` are append-only rows that carry only ``id`` and
``created_at``, so their TypedDicts deliberately omit ``updated_at`` and
``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PARTNER_MANAGER = "PartnerManager"
    CONTRACTS_OFFICER = "ContractsOfficer"
    REVENUE_ACCOUNTANT = "RevenueAccountant"
    FRAUD_ANALYST = "FraudAnalyst"
    ISSUER_REPRESENTATIVE = "IssuerRepresentative"
    MEMBER = "Member"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class RevenueRecognitionState(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    LOCKED = "LOCKED"


class BreakagePolicyMode(str, Enum):
    HISTORICAL_ATTRITION = "HISTORICAL_ATTRITION"
    FORWARD_EXPECTATION = "FORWARD_EXPECTATION"


class IssuerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class IssuerSuspensionReason(str, Enum):
    NONE = "NONE"
    CAP_BREACH = "CAP_BREACH"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUER_REVIEW = "ISSUER_REVIEW"
    COUNTERED = "COUNTERED"
    RATIFIED = "RATIFIED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class HomeRegion(str, Enum):
    AMER = "AMER"
    EMEA = "EMEA"
    APAC = "APAC"


class EliteTier(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class SecurityState(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class StatusMatchState(str, Enum):
    NONE = "NONE"
    TRIAL = "TRIAL"
    CONFIRMED = "CONFIRMED"
    LAPSED = "LAPSED"


class QualificationState(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    CLOSED = "CLOSED"
    RESTATED = "RESTATED"


class TxnType(str, Enum):
    FLIGHT_EARN = "FLIGHT_EARN"
    CARD_SPEND_EARN = "CARD_SPEND_EARN"
    PARTNER_EARN = "PARTNER_EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    EXPIRY = "EXPIRY"
    ADJUSTMENT = "ADJUSTMENT"


class EarnChannel(str, Enum):
    FLIGHT = "FLIGHT"
    CARD_SPEND = "CARD_SPEND"
    PARTNER = "PARTNER"


class StackingMode(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    ADDITIVE = "ADDITIVE"
    MULTIPLICATIVE = "MULTIPLICATIVE"


class CampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class Cabin(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM = "PREMIUM"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class CapacityControlState(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    CLOSED = "CLOSED"


class FareClass(str, Enum):
    SAVER = "SAVER"
    FLEX = "FLEX"


class SurchargeBand(str, Enum):
    SURCHARGE_LOW = "SURCHARGE_LOW"
    SURCHARGE_MID = "SURCHARGE_MID"
    SURCHARGE_HIGH = "SURCHARGE_HIGH"


class BookingStatus(str, Enum):
    HELD = "HELD"
    TICKETED = "TICKETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class ReciprocityMode(str, Enum):
    FULL = "FULL"
    INBOUND_ONLY = "INBOUND_ONLY"
    OUTBOUND_ONLY = "OUTBOUND_ONLY"
    SUSPENDED = "SUSPENDED"


class AwardPricingMode(str, Enum):
    FIXED_CHART = "FIXED_CHART"
    DISTANCE_BAND = "DISTANCE_BAND"
    DYNAMIC_PASSTHROUGH = "DYNAMIC_PASSTHROUGH"


class ChangeType(str, Enum):
    EARN_STRUCTURE = "EARN_STRUCTURE"
    AWARD_PRICING = "AWARD_PRICING"
    ELITE_THRESHOLD = "ELITE_THRESHOLD"
    EXPIRY_POLICY = "EXPIRY_POLICY"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    IN_GRANDFATHER = "IN_GRANDFATHER"
    EFFECTIVE = "EFFECTIVE"
    ROLLED_BACK = "ROLLED_BACK"


class CaseType(str, Enum):
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"
    MILE_BROKERING = "MILE_BROKERING"
    VELOCITY_ANOMALY = "VELOCITY_ANOMALY"


class FraudCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class StatusMatchOutcome(str, Enum):
    CONFIRM = "CONFIRM"
    LAPSE = "LAPSE"


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
class TierScheduleEntry(TypedDict):
    threshold_miles: int
    price_per_mile_centicents: int


class LoyaltyProgram(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    currency_code: str
    current_period: str
    breakage_policy_mode: str
    saver_share_default_bps: int
    revenue_recognition_state: str
    outstanding_miles: int
    deferred_revenue_cents: int
    last_breakage_rate_bps: int
    lifetime_breakage_income_cents: int


class CoBrandIssuer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    name: str
    annual_mile_purchase_cap_miles: int
    aggregate_committed_miles: int
    status: str
    suspension_reason: str


class MileSaleAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    issuer_id: str
    supersedes_agreement_id: Optional[str]
    term_start_date: str
    term_end_date: str
    committed_volume_miles: int
    tier_schedule: List[TierScheduleEntry]
    status: str
    negotiation_round: int
    countered_price_per_mile_centicents: Optional[int]
    countered_committed_volume_miles: Optional[int]
    drawn_miles: int
    prepayment_balance_miles: int
    negotiated_by_user_id: Optional[str]
    ratified_by_user_id: Optional[str]


class MilePurchaseOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    order_miles: int
    drawn_miles_before: int
    provisional_tier_price_centicents: int
    gross_amount_cents: int
    final_amount_cents: Optional[int]
    volume_true_up_cents: int
    net_amount_cents: Optional[int]
    fulfillment_status: str
    settlement_status: str
    posted_period: Optional[str]
    reversal_reason: Optional[str]


class MemberAccount(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    external_member_ref: str
    home_region: str
    cycle_year: int
    rollover_carried_in: int
    elite_tier: str
    security_state: str
    status_match_state: str
    status_match_tier: Optional[str]
    status_match_expires_at: Optional[str]
    qualification_state: str
    qualifying_miles_ytd: int
    qualifying_segments_ytd: int
    qualifying_spend_cents_ytd: int
    rollover_carried_out: int
    awarded_tier_at_close: Optional[str]
    mile_balance: int
    lifetime_miles: int
    risk_score: int


class MileTransaction(TypedDict):
    """Append-only ledger row: only ``id`` and ``created_at`` are common fields."""
    id: str
    created_at: str
    member_id: str
    promotion_id: Optional[str]
    award_booking_id: Optional[str]
    reverses_transaction_id: Optional[str]
    txn_type: str
    base_miles: int
    qualifying_spend_cents: int
    segments: int
    activity_date: str
    elite_tier_at_earn: str
    tier_bonus_miles: int
    promo_multiplier_bps: int
    stacking_mode_applied: Optional[str]
    bonus_miles: int
    total_miles: int
    qualifying_miles_credited: int
    posted_period: str


class PromotionCampaign(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    code: str
    earn_channel: str
    multiplier_bps: int
    stacking_mode: str
    bonus_cap_miles: Optional[int]
    accrued_bonus_miles: int
    window_start: str
    window_end: str
    status: str
    cancellation_reason: Optional[str]


class AwardInventoryWindow(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    route_code: str
    cabin: str
    window_start_date: str
    window_end_date: str
    authorized_seats: int
    saver_seat_share_bps: int
    seats_held: int
    seats_confirmed: int
    saver_seats_consumed: int
    load_factor_bps: int
    capacity_control_state: str
    demand_multiplier_bps: int


class AwardBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    member_id: str
    window_id: str
    partner_airline_id: Optional[str]
    travel_date: str
    seats: int
    fare_class: str
    chart_miles_per_seat: int
    demand_multiplier_bps_applied: int
    partner_uplift_bps_applied: int
    surcharge_band: str
    elite_discount_bps_applied: int
    quoted_miles: int
    cash_surcharge_cents: int
    partner_settlement_cents: int
    partner_settled: bool
    hold_expires_at: str
    status: str


class PartnerAirline(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    iata_code: str
    settlement_rate_centicents_per_mile: int
    reciprocity_mode: str
    award_pricing_mode: str
    net_settlement_balance_cents: int
    settled_booking_count: int
    last_settlement_run_at: Optional[str]


class ProgramChangeNotice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    change_type: str
    effective_at: str
    grandfather_until: Optional[str]
    grandfathered_tier_floor: Optional[str]
    announced_at: Optional[str]
    notice_days: int
    exposed_member_count: int
    member_reaction_index: int
    status: str
    rollback_reason: Optional[str]


class FraudCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    member_id: str
    case_type: str
    login_geo_velocity: int
    redemption_velocity_24h: int
    brokering_pattern_hits: int
    dormancy_days: int
    detection_score: int
    freeze_applied: bool
    clawback_miles: int
    opened_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    status: str


class DeferredRevenuePosting(TypedDict):
    """Immutable accounting row: only ``id`` and ``created_at`` are common fields."""
    id: str
    created_at: str
    program_id: str
    period: str
    method: Optional[str]
    method_applied: str
    outstanding_miles_snapshot: int
    expired_miles_trailing: int
    redeemed_miles_trailing: int
    issued_miles_trailing: int
    breakage_rate_bps: int
    deferred_balance_before_cents: int
    breakage_income_cents: int
    deferred_balance_after_cents: int


class EpochReport(TypedDict):
    epoch_at: str
    holds_expired: int
    campaigns_launched: int
    campaigns_ended: int
    status_matches_lapsed: int
    notices_advanced: int
    agreements_expired: int
    windows_recomputed: int
