"""Domain types for the Hotel Loyalty Owner Reimbursement API.

Status enums, entity TypedDicts and the operator role enum, all named exactly as
the PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    HOTEL_OWNER = "HotelOwner"
    MEMBER = "Member"
    MEMBER_CARE_AGENT = "MemberCareAgent"
    PROGRAM_AUDITOR = "ProgramAuditor"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class HotelStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    FEE_DELINQUENT = "FEE_DELINQUENT"
    TERMINATED = "TERMINATED"


class MarketTier(str, Enum):
    URBAN = "URBAN"
    RESORT = "RESORT"
    SELECT = "SELECT"


class RateCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    CORPORATE_NEGOTIATED = "CORPORATE_NEGOTIATED"
    GROUP = "GROUP"
    OPAQUE_WHOLESALE = "OPAQUE_WHOLESALE"
    EMPLOYEE_COMP = "EMPLOYEE_COMP"
    AWARD = "AWARD"


class Season(str, Enum):
    STANDARD = "STANDARD"
    PEAK = "PEAK"


class EliteTier(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BlackoutScope(str, Enum):
    ALL_REDEMPTIONS = "ALL_REDEMPTIONS"
    STANDARD_ONLY = "STANDARD_ONLY"


class BlackoutWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class StayStatus(str, Enum):
    PENDING_POSTING = "PENDING_POSTING"
    POSTED_QUALIFYING = "POSTED_QUALIFYING"
    POSTED_NON_QUALIFYING = "POSTED_NON_QUALIFYING"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    VOID = "VOID"


class BenefitType(str, Enum):
    UPGRADE = "UPGRADE"
    BREAKFAST = "BREAKFAST"
    LATE_CHECKOUT = "LATE_CHECKOUT"


class DeliveryStatus(str, Enum):
    OBLIGATED = "OBLIGATED"
    DELIVERED = "DELIVERED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    DENIED_FINAL = "DENIED_FINAL"
    WAIVED = "WAIVED"


class FulfillmentStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    STAYED = "STAYED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReimbursementStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    ACCRUED = "ACCRUED"
    BATCHED = "BATCHED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class LedgerEntryType(str, Enum):
    EARN_BASE = "EARN_BASE"
    EARN_BONUS = "EARN_BONUS"
    PURCHASE = "PURCHASE"
    PARTNER_SALE = "PARTNER_SALE"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    GOODWILL = "GOODWILL"


class PartnerType(str, Enum):
    CO_BRAND_ISSUER = "CO_BRAND_ISSUER"
    AIRLINE = "AIRLINE"
    RETAIL = "RETAIL"


class PurchaseChannel(str, Enum):
    CO_BRAND_CARD = "CO_BRAND_CARD"
    DIRECT_PURCHASE = "DIRECT_PURCHASE"
    PARTNER_SALE = "PARTNER_SALE"


class PurchaseStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class FundStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    IMPAIRED = "IMPAIRED"


class ComplaintSubjectType(str, Enum):
    BENEFIT_DENIAL = "BENEFIT_DENIAL"
    POINT_SHORTFALL = "POINT_SHORTFALL"
    BLACKOUT_DISPUTE = "BLACKOUT_DISPUTE"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_GOODWILL = "RESOLVED_GOODWILL"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class AdjudicationOutcome(str, Enum):
    DELIVERY_ORDERED = "DELIVERY_ORDERED"
    DENIAL_UPHELD = "DENIAL_UPHELD"


# ---------------------------------------------------------------------------
# Entities that carry id + created_at + updated_at + version
# ---------------------------------------------------------------------------


class Hotel(TypedDict):
    id: str
    name: str
    brand_code: str
    market_tier: str
    program_fee_pct: float
    rooms_count: int
    trailing_12m_occupancy_pct: float
    trailing_12m_adr_cents: int
    status: str
    fee_ledger_balance_cents: int
    reimbursement_owed_cents: int
    benefit_recovery_owed_cents: int
    benefit_denial_count: int
    blackout_days_used_current_year: int
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict):
    id: str
    hotel_id: str
    start_date: str
    end_date: str
    scope: str
    status: str
    day_count: int
    revoke_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    enrollment_date: str
    elite_tier: str
    qualifying_nights_ytd: int
    qualifying_revenue_cents_ytd: int
    point_balance: int
    lifetime_points_earned: int
    points_purchased_current_year: int
    created_at: str
    updated_at: str
    version: int


class Stay(TypedDict):
    id: str
    member_id: str
    hotel_id: str
    rate_plan_id: str
    checkin_date: str
    checkout_date: str
    nights: int
    room_revenue_cents: int
    incidental_revenue_cents: int
    tier_at_checkin: str
    status: str
    base_points_awarded: int
    bonus_points_awarded: int
    program_fee_assessed_cents: int
    bonus_multiplier_applied: float
    dispute_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EliteBenefitDelivery(TypedDict):
    id: str
    stay_id: str
    benefit_type: str
    status: str
    cost_recovery_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    member_id: str
    hotel_id: str
    batch_id: Optional[str]
    checkin_date: str
    checkout_date: str
    nights: int
    season: str
    points_per_night_applied: int
    award_allotment_applied: int
    points_charged: int
    cash_copay_cents: int
    fulfillment_status: str
    reimbursement_status: str
    estimated_reimbursement_cents: int
    settled_reimbursement_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementBatch(TypedDict):
    id: str
    hotel_id: str
    period_month: str
    status: str
    item_count: int
    gross_reimbursement_cents: int
    fee_offset_base_cents: int
    delinquency_surcharge_cents: int
    total_fee_offset_cents: int
    net_payable_cents: int
    occupancy_pct_at_release: float
    adr_cents_at_release: int
    released_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointPurchase(TypedDict):
    id: str
    member_id: str
    partner_id: Optional[str]
    channel: str
    points_quantity: int
    volume_discount_pct: float
    cash_due_cents: int
    bonus_points: int
    status: str
    refund_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict):
    id: str
    name: str
    partner_type: str
    points_cost_per_1000_cents: int
    monthly_cap_points: int
    purchased_points_mtd: int
    created_at: str
    updated_at: str
    version: int


class ProgramFund(TypedDict):
    id: str
    cash_balance_cents: int
    outstanding_points: int
    breakage_rate_pct: float
    point_liability_cents: int
    solvency_ratio: float
    status: str
    last_revalued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberComplaint(TypedDict):
    id: str
    member_id: str
    related_delivery_id: Optional[str]
    subject_type: str
    description: str
    status: str
    info_request_count: int
    goodwill_points_granted: int
    resolution: Optional[str]
    adjudication_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: these carry ONLY id and created_at
# ---------------------------------------------------------------------------


class RatePlan(TypedDict):
    id: str
    hotel_id: str
    rate_code: str
    rate_category: str
    base_earn_rate_per_dollar: float
    is_qualifying: bool
    counts_toward_elite: bool
    program_fee_eligible: bool
    created_at: str


class RedemptionPricing(TypedDict):
    id: str
    hotel_id: str
    season: str
    window_start_date: str
    window_end_date: str
    points_per_night: int
    cash_copay_cents: int
    min_tier_required: str
    award_allotment_per_night: int
    created_at: str


class PointLedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    points: int
    source_stay_id: Optional[str]
    source_redemption_id: Optional[str]
    source_purchase_id: Optional[str]
    reversal_of_entry_id: Optional[str]
    adjustment_reason: Optional[str]
    liability_unit_cost_cents_per_1000: int
    created_at: str


APPEND_ONLY_ENTITIES = ("RatePlan", "RedemptionPricing", "PointLedgerEntry")
