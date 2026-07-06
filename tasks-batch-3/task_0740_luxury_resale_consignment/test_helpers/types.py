"""Domain types for the Luxury Resale Consignment API.

Entity TypedDicts, status enums, and the role enum. Every persisted resource
carries the four common system fields (id, created_at, updated_at, version) per
PRD §2.4, so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---------------------------------------------------
class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    SELLER = "Seller"
    BUYER = "Buyer"
    AUTHENTICATOR = "Authenticator"
    CONCIERGE_AGENT = "ConciergeAgent"


# --- Status / enum domains --------------------------------------------------
class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SellerTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"
    ELITE = "ELITE"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class Category(str, Enum):
    HANDBAGS = "HANDBAGS"
    WATCHES = "WATCHES"
    JEWELRY = "JEWELRY"
    APPAREL = "APPAREL"
    SHOES = "SHOES"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class IntakeChannel(str, Enum):
    DROP_OFF = "DROP_OFF"
    PICKUP = "PICKUP"


class ItemStatus(str, Enum):
    INTAKE_REQUESTED = "INTAKE_REQUESTED"
    RECEIVED = "RECEIVED"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


class AuthenticityVerdict(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    COUNTERFEIT = "COUNTERFEIT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SaleChannel(str, Enum):
    DIRECT = "DIRECT"
    OFFER = "OFFER"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


class DisputeType(str, Enum):
    AUTHENTICITY = "AUTHENTICITY"
    CONDITION = "CONDITION"
    CHANGE_OF_MIND = "CHANGE_OF_MIND"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    RESOLVED_BUYER = "RESOLVED_BUYER"
    RESOLVED_SELLER = "RESOLVED_SELLER"


class DisputeOutcome(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class PickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


# --- Entity TypedDicts ------------------------------------------------------
class Seller(TypedDict):
    id: str
    display_name: str
    email: str
    status: str
    tier: str
    lifetime_net_sales_cents: int
    pending_payout_cents: int
    released_payout_cents: int
    reversed_payout_cents: int
    payout_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    display_name: str
    email: str
    status: str
    lifetime_purchases_cents: int
    created_at: str
    updated_at: str
    version: int


class CategoryPolicy(TypedDict):
    id: str
    category: str
    base_commission_pct: float
    buyer_fee_pct: float
    buyer_fee_flat_cents: int
    return_window_days: int
    min_offer_pct: float
    listable_min_condition_grade: str
    pickup_insurance_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentItem(TypedDict):
    id: str
    seller_id: str
    category: str
    brand: str
    title: str
    declared_value_cents: int
    intake_channel: str
    status: str
    authenticity_verdict: Optional[str]
    condition_grade: Optional[str]
    authenticator_id: Optional[str]
    authenticated_at: Optional[str]
    listable: bool
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    item_id: str
    seller_id: str
    category: str
    list_price_cents: int
    status: str
    commission_tier_locked: Optional[str]
    commission_rate_locked_pct: Optional[float]
    provisional_payout_cents: Optional[int]
    min_offer_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    amount_cents: int
    status: str
    counter_amount_cents: Optional[int]
    round_number: int
    agreed_price_cents: Optional[int]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    offer_id: Optional[str]
    sale_channel: str
    sale_price_cents: int
    commission_rate_pct: float
    commission_cents: int
    seller_net_payout_cents: int
    buyer_fee_cents: int
    tax_cents: int
    order_total_cents: int
    payment_status: str
    fulfillment_status: str
    delivered_at: Optional[str]
    return_window_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    sale_id: str
    seller_id: str
    amount_cents: int
    status: str
    scheduled_release_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    sale_id: str
    buyer_id: str
    type: str
    reason: str
    status: str
    outcome: Optional[str]
    refund_amount_cents: Optional[int]
    restocking_fee_cents: Optional[int]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Concierge(TypedDict):
    id: str
    name: str
    region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    plate: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupAppointment(TypedDict):
    id: str
    item_id: str
    concierge_id: str
    vehicle_id: str
    seller_id: str
    window_start: str
    window_end: str
    status: str
    declared_value_cents: int
    created_at: str
    updated_at: str
    version: int
