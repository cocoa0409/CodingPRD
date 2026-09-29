"""Domain types: status enums, the role enum and one TypedDict per entity.

PRD §2.4: every persisted resource carries a UUID ``id`` and a ``created_at``
timestamp, and almost every one additionally carries ``updated_at`` and an
integer ``version``. The single exception is ``TrialAbuseSignal``, which carries
only ``id`` and ``created_at`` — its TypedDict below deliberately omits
``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    RETAIL_PARTNER = "RetailPartner"
    TRIAL_SUPPORT_AGENT = "TrialSupportAgent"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    FINANCE_CONTROLLER = "FinanceController"
    PLATFORM_ADMIN = "PlatformAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRIAL_RESTRICTED = "TRIAL_RESTRICTED"
    BLOCKED = "BLOCKED"


class Firmness(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    FIRM = "FIRM"


class MattressSize(str, Enum):
    TWIN = "TWIN"
    QUEEN = "QUEEN"
    KING = "KING"


class UnwindPolicy(str, Enum):
    DEDUCT_RETAIL = "DEDUCT_RETAIL"
    DEDUCT_PRORATED = "DEDUCT_PRORATED"
    FORFEIT_NONE = "FORFEIT_NONE"


class PriceMatchPolicy(str, Enum):
    MATCH_TO_LOWEST = "MATCH_TO_LOWEST"
    MATCH_TO_ADVERTISED = "MATCH_TO_ADVERTISED"
    NO_MATCH = "NO_MATCH"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Channel(str, Enum):
    DTC = "DTC"
    RETAIL_PARTNER = "RETAIL_PARTNER"


class FulfillmentStatus(str, Enum):
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DAMAGED_REPORTED = "DAMAGED_REPORTED"
    REPLACED = "REPLACED"
    CLOSED = "CLOSED"


class TrialStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BREAK_IN = "BREAK_IN"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    TRIAL_EXPIRED = "TRIAL_EXPIRED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    KEPT = "KEPT"
    EXCHANGED = "EXCHANGED"


class ReturnReasonCode(str, Enum):
    COMFORT = "COMFORT"
    DAMAGE = "DAMAGE"
    PRICE = "PRICE"
    OTHER = "OTHER"


class ReturnLogisticsStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    PICKED_UP = "PICKED_UP"
    INSPECTED = "INSPECTED"
    DISPOSITIONED = "DISPOSITIONED"
    CANCELLED = "CANCELLED"


class ReturnFinancialStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    RELEASED = "RELEASED"
    VOID = "VOID"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class DispositionChoice(str, Enum):
    PENDING = "PENDING"
    DONATION = "DONATION"
    RECYCLE = "RECYCLE"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class DispositionPartnerType(str, Enum):
    CHARITY = "CHARITY"
    RECYCLER = "RECYCLER"


class SoilPolicy(str, Enum):
    REJECT_SOILED = "REJECT_SOILED"
    ACCEPT_SOILED = "ACCEPT_SOILED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class RefundStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class ExchangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class SettlementDirection(str, Enum):
    CHARGE_CUSTOMER = "CHARGE_CUSTOMER"
    CREDIT_CUSTOMER = "CREDIT_CUSTOMER"
    EVEN = "EVEN"


class QualityClaimType(str, Enum):
    SHIPPING_DAMAGE = "SHIPPING_DAMAGE"
    COMPRESSION_RECOVERY = "COMPRESSION_RECOVERY"
    WARRANTY_INDENTATION = "WARRANTY_INDENTATION"


class MeasurementMethod(str, Enum):
    STRAIGHTEDGE_PHOTO = "STRAIGHTEDGE_PHOTO"
    LASER_SCAN = "LASER_SCAN"


class QualityClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class QualityClaimResolution(str, Enum):
    PENDING = "PENDING"
    REPLACEMENT = "REPLACEMENT"
    CREDIT = "CREDIT"
    DENIED = "DENIED"


class AttributionClaimType(str, Enum):
    SALES_ATTRIBUTION = "SALES_ATTRIBUTION"
    PRICE_MATCH = "PRICE_MATCH"


class AttributionClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AbuseSignalType(str, Enum):
    REPEAT_RETURN = "REPEAT_RETURN"
    HOUSEHOLD_MATCH = "HOUSEHOLD_MATCH"
    SHORT_TRIAL = "SHORT_TRIAL"
    MULTI_CHANNEL = "MULTI_CHANNEL"


class CommonFields(TypedDict):
    """PRD §2.4 — the four fields carried by every entity except TrialAbuseSignal."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Customer(CommonFields):
    email: str
    full_name: str
    household_hash: str
    status: str
    lifetime_trial_count: int
    completed_return_count: int
    abuse_score_rolling: int
    abuse_score_lifetime: int
    trial_block_until: Optional[str]
    signal_count: int


class MattressModel(CommonFields):
    sku: str
    name: str
    firmness: str
    size: str
    list_price_cents: int
    break_in_nights: int
    trial_nights: int
    indentation_warranty_threshold_mm: float
    warranty_years: int
    donation_eligible: bool


class PromotionBundle(CommonFields):
    code: str
    accessory_retail_cents: int
    percent_off_bps: int
    gift_card_cents: int
    unwind_policy: str
    requires_accessory_return: bool


class RetailPartner(CommonFields):
    name: str
    region_code: str
    commission_bps: int
    price_match_policy: str
    attribution_window_days: int
    status: str


class TrialOrder(CommonFields):
    customer_id: str
    model_id: str
    bundle_id: Optional[str]
    retail_partner_id: Optional[str]
    exchanged_from_order_id: Optional[str]
    channel: str
    gross_price_cents: int
    bundle_discount_cents: int
    paid_amount_cents: int
    fulfillment_status: str
    trial_status: str
    delivered_at: Optional[str]
    break_in_ends_at: Optional[str]
    trial_ends_at: Optional[str]
    nights_slept: Optional[int]
    exchange_chain_depth: int
    goodwill_credit_cents: int
    price_match_credit_cents: int
    refunded_total_cents: int
    outstanding_refundable_cents: int
    retained_amount_cents: int


class ReturnCase(CommonFields):
    order_id: str
    reason_code: str
    requested_at: str
    logistics_status: str
    financial_status: str
    picked_up_at: Optional[str]
    nights_used: Optional[int]
    condition_grade: Optional[str]
    soil_flag: Optional[bool]
    accessory_returned: Optional[bool]
    disposition: str
    proration_deduction_cents: Optional[int]
    bundle_unwind_cents: Optional[int]
    damage_offset_cents: Optional[int]
    provisional_refund_cents: Optional[int]
    final_refund_cents: Optional[int]


class PickupRoute(CommonFields):
    region_code: str
    route_date: str
    window_start_at: str
    window_end_at: str
    buffer_minutes: int
    capacity_units: int
    booked_units: int
    available_units: int
    status: str


class PickupAppointment(CommonFields):
    route_id: str
    return_case_id: str
    slot_start_at: str
    slot_end_at: str
    units: int
    status: str
    closed_at: Optional[str]


class DispositionPartner(CommonFields):
    name: str
    partner_type: str
    region_code: str
    daily_intake_capacity_units: int
    accepts_condition_grades: List[str]
    soil_policy: str
    priority_rank: int
    recycle_fee_cents_per_unit: int
    status: str


class DispositionAssignment(CommonFields):
    return_case_id: str
    partner_id: str
    intake_date: str
    disposition_type: str
    units: int
    fee_cents: int
    fallback_applied: bool
    status: str


class RefundAuthorization(CommonFields):
    return_case_id: str
    order_id: str
    supersedes_refund_id: Optional[str]
    gross_refundable_cents: int
    proration_deduction_cents: int
    bundle_unwind_cents: int
    damage_offset_cents: int
    net_refund_cents: int
    authorized_by_user_id: str
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    status: str


class ComfortExchange(CommonFields):
    original_order_id: str
    target_model_id: str
    replacement_order_id: Optional[str]
    sequence_number: int
    raw_price_difference_cents: int
    exchange_fee_cents: int
    tier_credit_cents: int
    price_difference_cents: int
    settlement_direction: str
    status: str
    decline_note: Optional[str]


class QualityClaim(CommonFields):
    order_id: str
    claim_type: str
    photo_evidence_count: int
    measurement_method: Optional[str]
    measured_indentation_mm: Optional[float]
    reported_at: str
    evidence_round_count: int
    ownership_years: Optional[int]
    coverage_bps: Optional[int]
    credit_cents: Optional[int]
    resolution: str
    status: str
    approved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]


class AttributionClaim(CommonFields):
    partner_id: str
    order_id: str
    claim_type: str
    competitor_price_cents: Optional[int]
    evidence_url_count: int
    submitted_at: str
    revision_round_count: int
    commission_cents: Optional[int]
    price_match_credit_cents: Optional[int]
    status: str
    resolved_at: Optional[str]


class TrialAbuseSignal(TypedDict):
    """PRD §2.4 — a TrialAbuseSignal carries only ``id`` and ``created_at``."""

    id: str
    created_at: str
    customer_id: str
    signal_type: str
    recorded_at: str
    weight: int
    source_note: Optional[str]


class RefundSummary(TypedDict):
    """PRD §3.8 — the computed refund-summary read."""

    variant_in_effect: str
    gross_refundable_cents: int
    proration_deduction_cents: int
    bundle_unwind_cents: int
    damage_offset_cents: int
    provisional_refund_cents: int
    final_refund_cents: int
    variant_delta_cents: int
