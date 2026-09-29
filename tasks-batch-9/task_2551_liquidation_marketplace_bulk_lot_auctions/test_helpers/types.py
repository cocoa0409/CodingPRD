"""Domain types for the liquidation marketplace API: status enums, role enum,
and entity TypedDicts.

Every name here is spelled exactly as the PRD spells it.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER_OPS = "SellerOps"
    BUYER = "Buyer"
    MARKETPLACE_OPS = "MarketplaceOps"
    TRUST_SAFETY = "TrustSafety"


# ─── Status enums ─────────────────────────────────────

class SellerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MANIFEST_PROBATION = "MANIFEST_PROBATION"
    SUSPENDED = "SUSPENDED"


class CommissionTier(str, Enum):
    TIER_STANDARD = "TIER_STANDARD"
    TIER_PREFERRED = "TIER_PREFERRED"
    TIER_PROBATION = "TIER_PROBATION"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class BusinessVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    MANIFEST_IN_REVIEW = "MANIFEST_IN_REVIEW"
    MANIFEST_APPROVED = "MANIFEST_APPROVED"
    MANIFEST_REJECTED = "MANIFEST_REJECTED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RELIST_PENDING = "RELIST_PENDING"
    VOIDED = "VOIDED"


class ManifestLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED_SOLD = "CLOSED_SOLD"
    CLOSED_NO_SALE = "CLOSED_NO_SALE"


class ListingFormat(str, Enum):
    AUCTION = "AUCTION"
    FIXED_PRICE = "FIXED_PRICE"
    NEGOTIATED = "NEGOTIATED"


class ResaleChannel(str, Enum):
    MARKETPLACE_RESALE = "MARKETPLACE_RESALE"
    EXPORT_ONLY = "EXPORT_ONLY"
    DISCOUNT_RETAIL = "DISCOUNT_RETAIL"
    SCRAP_ONLY = "SCRAP_ONLY"


class BidStatus(str, Enum):
    STANDING = "STANDING"
    WINNING = "WINNING"
    SUPERSEDED = "SUPERSEDED"
    WON = "WON"
    LOST = "LOST"


class BidType(str, Enum):
    LIVE = "LIVE"
    PROXY = "PROXY"


class NegotiationStatus(str, Enum):
    AWAITING_SELLER = "AWAITING_SELLER"
    AWAITING_BUYER = "AWAITING_BUYER"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class OfferSide(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class SaleSource(str, Enum):
    AUCTION_CLOSE = "AUCTION_CLOSE"
    FIXED_PRICE_PURCHASE = "FIXED_PRICE_PURCHASE"
    NEGOTIATED_ACCEPTANCE = "NEGOTIATED_ACCEPTANCE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUND_ISSUED = "REFUND_ISSUED"


class LogisticsStatus(str, Enum):
    AWAITING_APPOINTMENT = "AWAITING_APPOINTMENT"
    APPOINTMENT_SCHEDULED = "APPOINTMENT_SCHEDULED"
    PICKED_UP = "PICKED_UP"
    ABANDONED = "ABANDONED"


class SettlementBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class ClaimType(str, Enum):
    UNIT_SHORTAGE = "UNIT_SHORTAGE"
    CONDITION_MISGRADE = "CONDITION_MISGRADE"
    MISSING_SKU = "MISSING_SKU"


class CategoryCode(str, Enum):
    APPAREL = "APPAREL"
    ELECTRONICS = "ELECTRONICS"
    HOME_GOODS = "HOME_GOODS"
    TOYS = "TOYS"


class ConditionGrade(str, Enum):
    NEW_OVERSTOCK = "NEW_OVERSTOCK"
    CUSTOMER_RETURNS = "CUSTOMER_RETURNS"
    SALVAGE = "SALVAGE"


class DeclaredCondition(str, Enum):
    NEW = "NEW"
    LIKE_NEW = "LIKE_NEW"
    USED_GOOD = "USED_GOOD"
    DAMAGED = "DAMAGED"
    SALVAGE = "SALVAGE"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity below carries id / created_at / updated_at / version, except
# Offer, which the PRD declares carries only id and created_at.

class SellerAccount(TypedDict):
    id: str
    legal_name: str
    tax_id: str
    state_code: str
    contact_email: str
    account_status: str
    commission_tier: str
    commission_rate_bps: int
    gross_hammer_cents: int
    listed_retail_value_cents: int
    gross_recovery_rate: float
    net_proceeds_cents: int
    sold_retail_value_cents: int
    net_recovery_rate: float
    manifest_accuracy_avg: float
    scored_lot_count: int
    created_at: str
    updated_at: str
    version: int


class BuyerAccount(TypedDict):
    id: str
    legal_name: str
    tax_id: str
    state_code: str
    contact_email: str
    resale_certificate_number: Optional[str]
    resale_certificate_expires_on: Optional[str]
    requested_credit_limit_cents: int
    business_verification_status: str
    qualification_status: str
    approved_credit_limit_cents: int
    outstanding_exposure_cents: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    name: str
    state_code: str
    dock_door_count: int
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    name: str
    scac_code: str
    daily_pickup_capacity: int
    created_at: str
    updated_at: str
    version: int


class BrandPolicy(TypedDict):
    id: str
    brand_code: str
    permitted_channels: List[str]
    de_branding_required: bool
    debranding_fee_cents_per_unit: int
    prohibited_buyer_state_codes: List[str]
    embargo_start_at: Optional[str]
    embargo_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    seller_id: str
    warehouse_id: str
    brand_policy_id: Optional[str]
    title: str
    category_code: str
    condition_grade: str
    lot_status: str
    manifest_line_count: int
    declared_unit_count: int
    declared_retail_value_cents: int
    manifest_reviewed_by_user_id: Optional[str]
    manifest_accuracy_score: Optional[float]
    de_branding_required: bool
    created_at: str
    updated_at: str
    version: int


class ManifestLine(TypedDict):
    id: str
    lot_id: str
    sku: str
    unit_count: int
    unit_retail_cents: int
    declared_condition: str
    line_status: str
    verified_unit_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    lot_id: str
    listing_format: str
    resale_channel: str
    window_start_at: str
    window_end_at: str
    effective_close_at: str
    extension_count: int
    opening_bid_cents: Optional[int]
    reserve_price_cents: Optional[int]
    ask_price_cents: Optional[int]
    min_offer_cents: Optional[int]
    bid_increment_cents: int
    de_branding_attested: bool
    listing_status: str
    bid_count: int
    current_high_bid_cents: Optional[int]
    current_high_bidder_id: Optional[str]
    reserve_met: bool
    min_next_bid_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    bid_type: str
    amount_cents: Optional[int]
    max_amount_cents: Optional[int]
    ceiling_cents: int
    bid_status: str
    placed_at: str
    meets_reserve: bool
    created_at: str
    updated_at: str
    version: int


class Negotiation(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    negotiation_status: str
    round_number: int
    current_offer_cents: Optional[int]
    current_offer_side: Optional[str]
    current_offer_expires_at: Optional[str]
    accepted_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    """The PRD's one exception to the shared system fields: an Offer row
    carries only id and created_at - no updated_at and no version."""
    id: str
    negotiation_id: str
    offer_side: str
    amount_cents: int
    round_number: int
    expires_at: str
    created_at: str


class SaleOrder(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    sale_source: str
    hammer_price_cents: int
    buyer_premium_bps: int
    buyer_premium_cents: int
    pallet_count: int
    estimated_freight_cents: int
    actual_freight_cents: Optional[int]
    claim_credit_cents: int
    late_fee_cents: int
    pre_fee_total_cents: int
    total_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    paid_at: Optional[str]
    picked_up_at: Optional[str]
    abandoned_at: Optional[str]
    settlement_basis: str
    payment_status: str
    logistics_status: str
    payment_due_at: str
    pickup_deadline_at: str
    claim_window_closes_at: Optional[str]
    seller_commission_rate_bps: Optional[int]
    seller_commission_cents: Optional[int]
    seller_debranding_fee_cents: Optional[int]
    seller_net_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PickupAppointment(TypedDict):
    id: str
    sale_order_id: str
    warehouse_id: str
    carrier_id: str
    window_start_at: str
    window_end_at: str
    dock_door_number: int
    bol_number: str
    appointment_status: str
    completed_at: Optional[str]
    picked_up_unit_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    sale_order_id: str
    manifest_line_id: str
    claim_type: str
    claimed_units: int
    verified_units: Optional[int]
    evidence_item_count: int
    evidence_request_count: int
    claim_status: str
    refund_cents: int
    decided_by_user_id: Optional[str]
    reversed_by_user_id: Optional[str]
    filed_at: str
    created_at: str
    updated_at: str
    version: int
