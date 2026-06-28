"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and state machines. All primary resources
carry id/created_at/updated_at/version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum types ──────────────────────────────────────────────────

class CampaignType(str, Enum):
    CATALOG = "CATALOG"
    PLEDGE = "PLEDGE"
    EVENT = "EVENT"


class CampaignPosture(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"
    DISBURSED = "DISBURSED"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class OrderPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PledgeStatus(str, Enum):
    PROMISED = "PROMISED"
    RECORDED = "RECORDED"
    COLLECTED = "COLLECTED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class DisbursementStatus(str, Enum):
    RECORDED = "RECORDED"


class UserRole(str, Enum):
    CAMPAIGN_ADMIN = "CampaignAdmin"
    SELLER = "Seller"
    TREASURER = "Treasurer"
    SCHOOL_OFFICIAL = "SchoolOfficial"


# ─── Entity TypedDicts (all primary resources carry common fields) ─────────

class Campaign(TypedDict):
    id: str
    name: str
    campaign_type: str
    goal_cents: int
    profit_split_pct: float
    vendor_name: str
    starts_at: str
    ends_at: str
    posture: str
    gross_collected_cents: int
    forecast_gross_cents: int
    school_profit_cents: int
    vendor_payable_cents: int
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeTier(TypedDict):
    id: str
    campaign_id: str
    label: str
    threshold_cents: int
    prize_description: str
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    campaign_id: str
    display_name: str
    guardian_email: str
    share_slug: str
    status: str
    credited_cents: int
    earned_prize_tier_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    campaign_id: str
    sku: str
    name: str
    unit_price_cents: int
    unit_cost_cents: int
    stock_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    campaign_id: str
    seller_id: str
    buyer_name: str
    buyer_email: str
    lines: List[dict]
    payment_status: str
    fulfillment_status: str
    gross_cents: int
    tax_cents: int
    total_charged_cents: int
    receipt_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    campaign_id: str
    seller_id: str
    donor_name: str
    donor_email: str
    per_unit_cents: int
    flat_cents: int
    cap_cents: int
    units_recorded: int
    status: str
    pledged_amount_cents: int
    collected_cents: int
    receipt_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    campaign_id: str
    full_name: str
    email: str
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    campaign_id: str
    volunteer_id: Optional[str]
    role_label: str
    starts_at: str
    ends_at: str
    setup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    campaign_id: str
    school_amount_cents: int
    vendor_amount_cents: int
    memo: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
