"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Brewery / Winery Tasting Room & Club PRD (Sections 2-3).
Entities that carry id+created_at+updated_at+version are the primary resources;
the ComplianceLedgerEntry is the sole immutable audit event (id + created_at only).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class WineryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductionBatchStatus(str, Enum):
    FERMENTING = "FERMENTING"
    AGING = "AGING"
    BOTTLING = "BOTTLING"
    CLOSED = "CLOSED"
    DUMPED = "DUMPED"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AllocationReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MemberStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MembershipStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class MembershipBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class MembershipTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ShipmentHoldReason(str, Enum):
    NONE = "NONE"
    AGE = "AGE"
    STATE_LIMIT = "STATE_LIMIT"
    BILLING = "BILLING"
    WINERY_SUSPENDED = "WINERY_SUSPENDED"


class TastingOrderStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    REFUNDED = "REFUNDED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    SEATED = "SEATED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DistributionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SHIPPED = "SHIPPED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class BeverageClass(str, Enum):
    WINE = "WINE"
    BEER = "BEER"
    CIDER = "CIDER"


class LedgerEntryType(str, Enum):
    BOTTLING_REMOVAL = "BOTTLING_REMOVAL"
    EXCISE_ACCRUAL = "EXCISE_ACCRUAL"
    SHIPMENT_RELEASE = "SHIPMENT_RELEASE"
    DISTRIBUTION_REMOVAL = "DISTRIBUTION_REMOVAL"
    AGE_REJECTION = "AGE_REJECTION"
    STATE_LIMIT_REJECTION = "STATE_LIMIT_REJECTION"


class LedgerSubjectType(str, Enum):
    PRODUCTION_BATCH = "PRODUCTION_BATCH"
    SHIPMENT = "SHIPMENT"
    DISTRIBUTION_ORDER = "DISTRIBUTION_ORDER"
    TASTING_ORDER = "TASTING_ORDER"


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CELLAR_MANAGER = "CellarManager"
    CLUB_MANAGER = "ClubManager"
    TASTING_ROOM_STAFF = "TastingRoomStaff"
    MEMBER = "Member"


# ─── Primary resource TypedDicts (id+created_at+updated_at+version) ───

class Winery(TypedDict):
    id: str
    name: str
    ttb_permit_number: str
    home_state_code: str
    bulk_volume_gallons: float
    bottled_taxpaid_volume_gallons: float
    excise_tax_owed_cents: int
    loyalty_point_liability: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict):
    id: str
    winery_id: str
    lot_code: str
    beverage_class: str
    volume_in_gallons: float
    loss_gallons: float
    bottled_volume_gallons: float
    available_bulk_gallons: float
    abv_percent: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    winery_id: str
    source_batch_id: str
    sku: str
    vintage_year: int
    bottle_volume_ml: int
    list_price_cents: int
    is_age_restricted: bool
    on_hand_bottles: int
    allocated_bottles: int
    free_bottles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRelease(TypedDict):
    id: str
    product_id: str
    winery_id: str
    pool_bottles: int
    per_member_cap: int
    reserved_bottles: int
    committed_bottles: int
    available_bottles: int
    opens_at: str
    closes_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    winery_id: str
    full_name: str
    email: str
    date_of_birth: str
    ship_to_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    winery_id: str
    tier: str
    cadence_months: int
    bottles_per_shipment: int
    billing_status: str
    loyalty_points: int
    lifetime_bottles_shipped: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    membership_id: str
    winery_id: str
    release_id: str
    requested_bottles: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    loyalty_points_earned: int
    ship_to_state_code: str
    hold_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TastingOrder(TypedDict):
    id: str
    winery_id: str
    member_id: Optional[str]
    line_items: List[dict]
    guest_age_verified: bool
    subtotal_cents: int
    member_discount_cents: int
    loyalty_redeemed_cents: int
    total_cents: int
    loyalty_points_earned: int
    redeem_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    winery_id: str
    table_code: str
    party_size: int
    starts_at: str
    ends_at: str
    is_event: bool
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionOrder(TypedDict):
    id: str
    winery_id: str
    product_id: str
    retailer_license_number: str
    dest_state_code: str
    case_count: int
    bottles_ordered: int
    wholesale_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable audit event (id + created_at ONLY; no updated_at/version) ───

class ComplianceLedgerEntry(TypedDict):
    id: str
    winery_id: str
    entry_type: str
    subject_type: str
    subject_id: str
    volume_gallons: float
    excise_cents: int
    note: str
    created_at: str
