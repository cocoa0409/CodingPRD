"""Domain types for the Home Improvement Pro Desk & Contractor Account API.

Entity shapes, status enums and the role enum, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles                                                                        #
# --------------------------------------------------------------------------- #


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACTOR_ADMIN = "ContractorAdmin"
    PRO_DESK_ASSOCIATE = "ProDeskAssociate"
    CREDIT_MANAGER = "CreditManager"
    STORE_OPERATIONS = "StoreOperations"
    TAX_COMPLIANCE_OFFICER = "TaxComplianceOfficer"


# --------------------------------------------------------------------------- #
# Status / enum vocabularies                                                   #
# --------------------------------------------------------------------------- #


class DeliveryTruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ProAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"


class TierReviewMode(str, Enum):
    ROLLING_365_INCLUSIVE = "ROLLING_365_INCLUSIVE"
    PINNED_AT_REVIEW = "PINNED_AT_REVIEW"


class TierCode(str, Enum):
    MEMBER = "MEMBER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    DIAMOND = "DIAMOND"


class CreditLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class TaxExemptCertificateStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class JobQuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PaymentMethod(str, Enum):
    CREDIT_LINE = "CREDIT_LINE"
    CARD = "CARD"


class DeliveryMode(str, Enum):
    WILL_CALL = "WILL_CALL"
    DELIVERY = "DELIVERY"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RESERVED = "RESERVED"
    STAGED = "STAGED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CreditStatus(str, Enum):
    UNBILLED = "UNBILLED"
    AUTHORIZED = "AUTHORIZED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PriceSource(str, Enum):
    QUOTED = "QUOTED"
    TIER_DISCOUNTED = "TIER_DISCOUNTED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    ALLOCATED = "ALLOCATED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class WillCallStagingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STAGED = "STAGED"
    PICKED_UP = "PICKED_UP"
    EXPIRED = "EXPIRED"


class JobsiteAccessType(str, Enum):
    CURBSIDE = "CURBSIDE"
    DRIVEWAY = "DRIVEWAY"
    NARROW_ALLEY = "NARROW_ALLEY"
    CRANE_REQUIRED = "CRANE_REQUIRED"


class DeliveryAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class RebatePayoutStatus(str, Enum):
    ACCRUING = "ACCRUING"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ReturnReasonCode(str, Enum):
    OVER_ORDERED = "OVER_ORDERED"
    DAMAGED = "DAMAGED"
    JOB_CANCELLED = "JOB_CANCELLED"
    WRONG_ITEM = "WRONG_ITEM"


class ReturnValuationMode(str, Enum):
    QUOTED_TERM = "QUOTED_TERM"
    CURRENT_LIST = "CURRENT_LIST"


class ReturnRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CREDITED = "CREDITED"


# --------------------------------------------------------------------------- #
# Entity shapes                                                                #
#                                                                              #
# Every resource in this API carries id, created_at, updated_at and version.    #
# --------------------------------------------------------------------------- #


class Store(TypedDict):
    id: str
    store_code: str
    region_code: str
    state_code: str
    distance_rank: int
    will_call_bay_slots: int
    lift_gate_available: bool
    tax_rate_pct: float
    max_stage_hours: int
    created_at: str
    updated_at: str
    version: int


class StoreStock(TypedDict):
    id: str
    store_id: str
    sku: str
    on_hand_units: int
    reserved_units: int
    available_units: int
    list_unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryTruck(TypedDict):
    id: str
    store_id: str
    truck_code: str
    lift_gate_equipped: bool
    turnaround_buffer_minutes: int
    access_types_supported: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProAccount(TypedDict):
    id: str
    business_name: str
    home_store_id: str
    po_required: bool
    job_name_required: bool
    tier_review_mode: str
    baseline_volume_cents: int
    trailing_volume_cents: int
    tier_code: str
    tier_discount_pct: float
    tier_reviewed_at: str
    rebate_accrued_cents: int
    tax_exempt_state_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditLine(TypedDict):
    id: str
    pro_account_id: str
    limit_cents: int
    terms_days: int
    exposure_cents: int
    available_cents: int
    status: str
    frozen_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxExemptCertificate(TypedDict):
    id: str
    pro_account_id: str
    state_code: str
    certificate_number: str
    expires_on: str
    status: str
    verified_at: Optional[str]
    revoke_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobQuote(TypedDict):
    id: str
    pro_account_id: str
    originating_store_id: str
    job_name: str
    requested_term_days: int
    status: str
    round_count: int
    revision_count: int
    list_subtotal_cents: Optional[int]
    negotiated_total_cents: Optional[int]
    discount_depth_pct: Optional[float]
    term_days: Optional[int]
    term_start: Optional[str]
    term_end: Optional[str]
    authored_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    withdrawn_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    job_quote_id: str
    sku: str
    qty_units: int
    list_unit_price_cents: Optional[int]
    negotiated_unit_price_cents: Optional[int]
    line_list_subtotal_cents: Optional[int]
    line_negotiated_subtotal_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProOrder(TypedDict):
    id: str
    pro_account_id: str
    fulfillment_store_id: str
    job_quote_id: Optional[str]
    po_number: Optional[str]
    job_name: Optional[str]
    payment_method: str
    delivery_mode: str
    lift_gate_required: bool
    job_lot_required: bool
    resale_purchase: bool
    fulfillment_status: str
    credit_status: str
    tier_code_applied: Optional[str]
    list_subtotal_cents: Optional[int]
    subtotal_cents: Optional[int]
    discount_cents: Optional[int]
    freight_surcharge_cents: Optional[int]
    lift_gate_fee_cents: Optional[int]
    tax_cents: Optional[int]
    total_cents: Optional[int]
    tax_exempt_applied: bool
    priced_at: Optional[str]
    invoiced_at: Optional[str]
    fulfilled_at: Optional[str]
    credited_refund_cents: int
    credited_gross_refund_cents: int
    net_volume_cents: Optional[int]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    pro_order_id: str
    sku: str
    qty_units: int
    price_source: Optional[str]
    list_unit_price_cents: Optional[int]
    effective_unit_price_cents: Optional[int]
    line_subtotal_cents: Optional[int]
    fulfilled_units: int
    returned_units: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    pro_order_id: str
    order_line_id: str
    store_id: str
    sku: str
    qty_units: int
    status: str
    released_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WillCallStaging(TypedDict):
    id: str
    pro_order_id: str
    store_id: str
    stage_start: str
    stage_hours: int
    expires_at: str
    status: str
    picked_up_by: Optional[str]
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict):
    id: str
    pro_order_id: str
    delivery_truck_id: str
    window_start: str
    window_end: str
    jobsite_access_type: str
    status: str
    delivered_at: Optional[str]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebateAccrual(TypedDict):
    id: str
    pro_account_id: str
    period_start: str
    period_end: str
    accrued_cents: int
    clawed_back_cents: int
    payable_cents: int
    payout_status: str
    closed_at: Optional[str]
    payout_reference: Optional[str]
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    pro_order_id: str
    reason_code: str
    lines: List[dict]
    valuation_mode: Optional[str]
    gross_refund_cents: Optional[int]
    restocking_fee_pct: Optional[float]
    restocking_fee_cents: Optional[int]
    tax_refund_cents: Optional[int]
    refund_total_cents: Optional[int]
    status: str
    approved_by_user_id: Optional[str]
    denied_reason_code: Optional[str]
    credited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
