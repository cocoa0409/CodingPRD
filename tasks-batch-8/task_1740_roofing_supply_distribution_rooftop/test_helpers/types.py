"""Domain types: entity TypedDicts, status enums, role enum.

Common-field rule (PRD §2.5): every resource carries id + created_at; mutable
resources additionally carry updated_at + version. WarrantyRegistration is the
one deliberate exception — immutable, carrying only id + created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BRANCH_MANAGER = "BranchManager"
    SALES_REP = "SalesRep"
    DISPATCHER = "Dispatcher"
    CONTRACTOR = "Contractor"
    CREDIT_ANALYST = "CreditAnalyst"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    WAREHOUSE_CLERK = "WarehouseClerk"


class SurgeMode(str, Enum):
    NORMAL = "NORMAL"
    SURGE = "SURGE"


class BranchStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LIEN_DEFAULT = "LIEN_DEFAULT"


class PricingTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    VOLUME = "VOLUME"


class LienStatus(str, Enum):
    NONE = "NONE"
    NOTICE_FILED = "NOTICE_FILED"
    LIEN_RECORDED = "LIEN_RECORDED"
    RELEASED = "RELEASED"


class TakeoffStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    RETURN_ADJUSTED = "RETURN_ADJUSTED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"


class SlotWindow(str, Enum):
    AM = "AM"
    PM = "PM"


class EquipmentType(str, Enum):
    GROUND = "GROUND"
    ROOFTOP_CONVEYOR = "ROOFTOP_CONVEYOR"
    CRANE = "CRANE"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class SurgeEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    CREDITED = "CREDITED"


class Branch(TypedDict, total=False):
    id: str
    branch_code: str
    name: str
    rooftop_delivery_capacity_per_day: int
    conveyor_fleet_size: int
    crane_available: bool
    surge_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    manufacturer_name: str
    color_code: str
    bundles_per_square: float
    base_price_per_bundle_cents: int
    requires_certified_installer: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    branch_id: str
    product_id: str
    lot_code: str
    on_hand_bundles: int
    reserved_bundles: int
    available_bundles: int
    created_at: str
    updated_at: str
    version: int


class ContractorAccount(TypedDict, total=False):
    id: str
    company_name: str
    credit_limit_cents: int
    open_balance_cents: int
    pending_delivery_hold_cents: int
    lien_hold_cents: int
    credit_available_cents: int
    pricing_tier: str
    manufacturer_certifications: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class JobAccount(TypedDict, total=False):
    id: str
    contractor_account_id: str
    job_name: str
    site_address: str
    job_balance_cents: int
    lien_status: str
    lien_notice_amount_cents: int
    notice_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialTakeoff(TypedDict, total=False):
    id: str
    job_account_id: str
    product_id: str
    roof_squares: float
    waste_factor_pct: float
    valley_ridge_linear_feet: int
    estimated_bundles: int
    estimated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    job_account_id: str
    takeoff_id: str
    branch_id: str
    storm_surge_event_id: Optional[str]
    subtotal_cents: int
    discount_cents: int
    delivery_fee_cents: int
    surge_premium_cents: int
    total_cents: int
    fulfillment_status: str
    payment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    inventory_lot_id: Optional[str]
    quantity_bundles: int
    delivered_bundles: int
    returned_bundles: int
    unit_price_cents: int
    extended_price_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict, total=False):
    id: str
    branch_id: str
    slot_date: str
    window: str
    equipment_type: str
    capacity: int
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    order_id: str
    delivery_slot_id: str
    equipment_type: str
    bundle_count: int
    fee_cents: int
    crane_fee_cents: int
    attempt_count: int
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StormSurgeEvent(TypedDict, total=False):
    id: str
    branch_id: str
    event_name: str
    starts_at: str
    ends_at: str
    surge_multiplier_pct: int
    allocation_pool_bundles: int
    allocated_bundles: int
    remaining_pool_bundles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    storm_surge_event_id: str
    contractor_account_id: str
    product_id: str
    requested_bundles: int
    granted_bundles: int
    consumed_bundles: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    quantity_bundles: int
    opened_bundles: int
    lot_match_verified: bool
    credit_amount_cents: int
    restocking_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    delivery_id: str
    claimed_bundles: int
    claim_amount_cents: int
    approved_amount_cents: int
    evidence_note: str
    review_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    """Immutable record (PRD §2.5): carries only id + created_at — no
    updated_at, no version."""
    id: str
    order_id: str
    manufacturer_name: str
    registered_bundles: int
    certification_verified: bool
    registered_at: str
    created_at: str
