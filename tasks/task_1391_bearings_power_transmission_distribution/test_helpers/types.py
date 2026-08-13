"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PHASEOUT = "PHASEOUT"
    OBSOLETE = "OBSOLETE"


class ProductFamily(str, Enum):
    BEARING = "BEARING"
    GEARBOX = "GEARBOX"
    BELT = "BELT"
    CHAIN = "CHAIN"
    SEAL = "SEAL"


class InterchangeClass(str, Enum):
    EXACT = "EXACT"
    DIMENSIONAL = "DIMENSIONAL"
    FUNCTIONAL = "FUNCTIONAL"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PriceBasis(str, Enum):
    LIST_LESS = "LIST_LESS"
    CONTRACT_FIXED = "CONTRACT_FIXED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class BranchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PriceFileStatus(str, Enum):
    PENDING = "PENDING"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class PriceVariant(str, Enum):
    ORDER_DATE = "ORDER_DATE"
    SHIP_DATE = "SHIP_DATE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FULLY_SOURCED = "FULLY_SOURCED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class ExpediteTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    RUSH = "RUSH"
    EMERGENCY = "EMERGENCY"


class SourcingStatus(str, Enum):
    PENDING_SOURCING = "PENDING_SOURCING"
    STOCK_RESERVED = "STOCK_RESERVED"
    FACTORY_ORDERED = "FACTORY_ORDERED"
    FACTORY_RECEIVED = "FACTORY_RECEIVED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    PREEMPTED = "PREEMPTED"


class CallOutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    FULFILLED = "FULFILLED"
    STOCK_UNAVAILABLE = "STOCK_UNAVAILABLE"
    CANCELLED = "CANCELLED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BillingVariant(str, Enum):
    CONSUMPTION_FIFO = "CONSUMPTION_FIFO"
    MONTHLY_SNAPSHOT = "MONTHLY_SNAPSHOT"


class ConsumptionStatus(str, Enum):
    REPORTED = "REPORTED"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    CREDITED = "CREDITED"


class FailureMode(str, Enum):
    FATIGUE = "FATIGUE"
    CONTAMINATION = "CONTAMINATION"
    MISALIGNMENT = "MISALIGNMENT"
    LUBRICATION = "LUBRICATION"
    BRINELLING = "BRINELLING"
    OTHER = "OTHER"


class Verdict(str, Enum):
    NONE = "NONE"
    CONFIRMED_DEFECT = "CONFIRMED_DEFECT"
    MISAPPLICATION = "MISAPPLICATION"
    WEAR_OUT = "WEAR_OUT"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_ANALYSIS = "UNDER_ANALYSIS"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CREDIT_ISSUED = "CREDIT_ISSUED"


class ReturnCondition(str, Enum):
    SURPLUS = "SURPLUS"
    OBSOLETE = "OBSOLETE"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    EXPIRED = "EXPIRED"


class ShopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    PRICING_ANALYST = "PricingAnalyst"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"
    COUNTER_SALES_REP = "CounterSalesRep"
    BRANCH_MANAGER = "BranchManager"
    ON_CALL_TECHNICIAN = "OnCallTechnician"
    WARRANTY_ANALYST = "WarrantyAnalyst"
    QUALITY_ENGINEER = "QualityEngineer"
    CUSTOMER_PLANT = "CustomerPlant"
    SERVICE_SHOP = "ServiceShop"


# --- Entity TypedDicts (common field set: id, created_at, updated_at, version) ---

class Product(TypedDict, total=False):
    id: str
    sku: str
    description: str
    family: str
    list_price_cents: int
    last_price_change_at: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InterchangeRecord(TypedDict, total=False):
    # Immutable record: carries ONLY id + created_at (no updated_at, no version)
    id: str
    competitor_part_number: str
    product_id: str
    interchange_class: str
    min_shaft_diameter_mm: float
    max_shaft_diameter_mm: float
    requires_engineering_review: bool
    created_at: str


class CustomerAccount(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    credit_status: str
    open_receivables_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerContract(TypedDict, total=False):
    id: str
    customer_id: str
    family: str
    price_basis: str
    discount_pct: float
    fixed_unit_price_cents: Optional[int]
    lag_protection_days: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict, total=False):
    id: str
    code: str
    timezone_offset_hours: int
    business_open_hour: int
    business_close_hour: int
    expedite_cutoff_hour: int
    after_hours_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BranchStock(TypedDict, total=False):
    id: str
    branch_id: str
    product_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    factory_lead_time_days: int
    reorder_point: int
    created_at: str
    updated_at: str
    version: int


class PriceFileVersion(TypedDict, total=False):
    id: str
    product_id: str
    new_list_price_cents: int
    effective_at: str
    published_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    branch_id: str
    price_variant: str
    fulfillment_status: str
    billing_status: str
    subtotal_cents: int
    expedite_fees_cents: int
    total_cents: int
    paid_cents: int
    priced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    qty: int
    expedite_tier: str
    unit_price_cents: Optional[int]
    price_protection_applied: bool
    expedite_fee_cents: int
    line_total_cents: int
    factory_ordered_at: Optional[str]
    shipped_at: Optional[str]
    sourcing_status: str
    created_at: str
    updated_at: str
    version: int


class StockReservation(TypedDict, total=False):
    id: str
    order_line_id: str
    branch_stock_id: str
    qty: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallOut(TypedDict, total=False):
    id: str
    branch_id: str
    customer_id: str
    product_id: str
    qty: int
    call_out_fee_cents: int
    parts_amount_cents: int
    total_charge_cents: int
    responder_id: Optional[str]
    preempted_reservation_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    branch_id: str
    product_id: str
    consigned_qty: int
    consumed_qty: int
    remaining_qty: int
    pinned_unit_price_cents: int
    billing_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentConsumption(TypedDict, total=False):
    id: str
    agreement_id: str
    qty: int
    reported_at: str
    unit_price_cents: Optional[int]
    billed_amount_cents: int
    offset_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    product_id: str
    order_line_id: Optional[str]
    consumption_id: Optional[str]
    filed_by: str
    failure_mode: str
    operating_hours: int
    qty: int
    verdict: str
    verdict_by: Optional[str]
    coverage_pct: float
    credit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    customer_id: str
    product_id: str
    branch_id: str
    qty: int
    condition: str
    original_unit_price_cents: int
    requested_by: str
    approved_by: Optional[str]
    eligible_credit_cents: int
    write_down_cents: int
    offset_applied_cents: int
    credit_memo_cents: int
    received_qty: int
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceShop(TypedDict, total=False):
    id: str
    name: str
    capabilities: List[str]
    region: str
    labor_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceReferral(TypedDict, total=False):
    id: str
    warranty_claim_id: str
    service_shop_id: str
    region: str
    quoted_amount_cents: Optional[int]
    referral_fee_cents: int
    declined_shop_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
