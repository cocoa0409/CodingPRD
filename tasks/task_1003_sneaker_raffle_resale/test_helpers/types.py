"""Domain types: entity TypedDicts, status enums, role enum.

All ten entity types are fully mutable and expose the four common fields
(id, created_at, updated_at, version), so every TypedDict below lists them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    BUYER = "Buyer"
    SELLER = "Seller"
    AUTHENTICATOR = "Authenticator"
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER_SERVICE = "CustomerService"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class SellerLevel(str, Enum):
    STANDARD = "STANDARD"
    PRO = "PRO"
    ELITE = "ELITE"


class ReleaseCategory(str, Enum):
    LIMITED = "LIMITED"
    GENERAL = "GENERAL"


class ReleaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    DRAWN = "DRAWN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RaffleResult(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"


class ClaimStatus(str, Enum):
    NONE = "NONE"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"


class ConditionGrade(str, Enum):
    DEADSTOCK = "DEADSTOCK"
    VNDS = "VNDS"
    USED = "USED"


class BoxGrade(str, Enum):
    PERFECT = "PERFECT"
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"
    MISSING = "MISSING"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class ConsignmentStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    RECEIVED = "RECEIVED"
    UNDER_AUTHENTICATION = "UNDER_AUTHENTICATION"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"


class PricingMode(str, Enum):
    FIXED = "FIXED"
    BID_ASK = "BID_ASK"


class BidStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"


class OrderSourceType(str, Enum):
    RAFFLE = "RAFFLE"
    FIXED = "FIXED"
    BID_MATCH = "BID_MATCH"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    IN_AUTHENTICATION = "IN_AUTHENTICATION"
    AUTHENTICATED = "AUTHENTICATED"
    FAILED_AUTH = "FAILED_AUTH"
    SHIPPED_TO_BUYER = "SHIPPED_TO_BUYER"
    VERIFIED = "VERIFIED"


class DisputeReason(str, Enum):
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    NOT_RECEIVED = "NOT_RECEIVED"
    INAUTHENTIC = "INAUTHENTIC"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_DENIED = "RESOLVED_DENIED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# --------------------------------------------------------------------------- #
class Account(TypedDict):
    id: str
    email: str
    full_name: str
    verification_status: str
    trust_score: float
    completed_sales_count: int
    seller_level: str
    balance_cents: int
    strikes: int
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    style_code: str
    name: str
    brand: str
    retail_price_cents: int
    release_category: str
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    sku_id: str
    allocated_quantity: int
    release_price_cents: int
    entry_opens_at: str
    entry_closes_at: str
    purchase_opens_at: str
    purchase_closes_at: str
    status: str
    entry_count: int
    winner_count: int
    reserved_units: int
    sold_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class RaffleEntry(TypedDict):
    id: str
    release_id: str
    account_id: str
    bot_risk_score: float
    bot_flag: bool
    fairness_score: float
    result: str
    claim_status: str
    claim_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authenticator(TypedDict):
    id: str
    name: str
    location_code: str
    daily_capacity: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentItem(TypedDict):
    id: str
    order_id: str
    seller_account_id: str
    sku_id: str
    authenticator_id: Optional[str]
    declared_condition_grade: str
    declared_box_grade: str
    declared_accessories_complete: bool
    authenticated_condition_grade: Optional[str]
    authenticated_box_grade: Optional[str]
    authenticated_accessories_complete: Optional[bool]
    declared_grade_score: float
    authenticated_grade_score: Optional[float]
    inspection_window_start: Optional[str]
    inspection_window_end: Optional[str]
    inspection_result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    sku_id: str
    seller_account_id: str
    size: str
    condition: str
    pricing_mode: str
    ask_price_cents: int
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    sku_id: str
    buyer_account_id: str
    size: str
    amount_cents: int
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    buyer_account_id: str
    sku_id: str
    seller_account_id: Optional[str]
    listing_id: Optional[str]
    bid_id: Optional[str]
    raffle_entry_id: Optional[str]
    source_type: str
    size: str
    sale_price_cents: int
    shipping_fee_cents: int
    transaction_fee_cents: int
    payment_processing_fee_cents: int
    buyer_total_cents: int
    downgrade_adjustment_cents: int
    provisional_payout_cents: int
    final_payout_cents: Optional[int]
    payment_status: str
    fulfillment_status: str
    dispute_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    order_id: str
    filed_by_account_id: str
    reason: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
