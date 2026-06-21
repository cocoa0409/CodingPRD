"""Domain types: entity TypedDicts, status enums, role enum.

All fourteen entity types carry id + created_at + updated_at + version per the
common conventions (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DEALER_MANAGER = "DealerManager"
    SALES_AGENT = "SalesAgent"
    SERVICE_ADVISOR = "ServiceAdvisor"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Enum value sets
# ---------------------------------------------------------------------------
class CreditTier(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"
    SUBPRIME = "SUBPRIME"


class ClassType(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    TRAVEL_TRAILER = "TRAVEL_TRAILER"
    FIFTH_WHEEL = "FIFTH_WHEEL"


class Acquisition(str, Enum):
    STOCK = "STOCK"
    CONSIGNMENT = "CONSIGNMENT"
    TRADE_IN = "TRADE_IN"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"
    CONSIGNMENT_RETURNED = "CONSIGNMENT_RETURNED"


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    PDI_PENDING = "PDI_PENDING"
    WALKTHROUGH = "WALKTHROUGH"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FinanceStatus(str, Enum):
    NONE = "NONE"
    CASH = "CASH"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PdiResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BayKind(str, Enum):
    REPAIR = "REPAIR"
    WASH_PDI = "WASH_PDI"


class ServiceOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class PlanKind(str, Enum):
    FACTORY = "FACTORY"
    EXTENDED = "EXTENDED"


class WarrantyPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class ApptKind(str, Enum):
    REPAIR = "REPAIR"
    PDI = "PDI"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StorageSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    STOP_SALE = "STOP_SALE"
    ADVISORY = "ADVISORY"


class RecallCampaignStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RecallRemedyStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (every entity carries id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Dealership(TypedDict):
    id: str
    name: str
    state_code: str
    doc_fee_cents: int
    sales_tax_rate_bps: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    dealership_id: str
    full_name: str
    email: str
    credit_tier: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    dealership_id: str
    vin: str
    model_year: int
    class_type: str
    acquisition: str
    consignor_customer_id: Optional[str]
    trade_in_origin_unit_id: Optional[str]
    list_price_cents: int
    consignment_floor_cents: Optional[int]
    consignment_fee_bps: Optional[int]
    open_recall_count: int
    status: str
    active_hold_deal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    dealership_id: str
    unit_id: str
    customer_id: str
    sales_agent_user_id: str
    sale_price_cents: int
    trade_unit_id: Optional[str]
    trade_allowance_cents: int
    trade_payoff_cents: int
    trade_recon_cost_cents: int
    net_trade_equity_cents: int
    dealer_book_equity_cents: int
    down_payment_cents: int
    doc_fee_cents: int
    tax_cents: int
    amount_financed_cents: int
    apr_bps: Optional[int]
    term_months: Optional[int]
    monthly_payment_cents: Optional[int]
    sale_status: str
    finance_status: str
    pdi_passed: bool
    created_at: str
    updated_at: str
    version: int


class PdiInspection(TypedDict):
    id: str
    dealership_id: str
    deal_id: str
    unit_id: str
    technician_user_id: str
    defects_found: int
    result: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    dealership_id: str
    name: str
    bay_kind: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    dealership_id: str
    unit_id: str
    customer_id: str
    advisor_user_id: str
    is_warranty: bool
    warranty_plan_id: Optional[str]
    labor_hours: float
    labor_rate_cents: int
    parts_subtotal_cents: int
    total_cents: int
    covered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartItem(TypedDict):
    id: str
    dealership_id: str
    sku: str
    name: str
    unit_price_cents: int
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    dealership_id: str
    service_order_id: str
    part_item_id: str
    quantity: int
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyPlan(TypedDict):
    id: str
    dealership_id: str
    unit_id: str
    customer_id: str
    plan_kind: str
    coverage_cap_cents: int
    deductible_cents: int
    consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    dealership_id: str
    service_bay_id: str
    service_order_id: Optional[str]
    deal_id: Optional[str]
    appt_kind: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageSlot(TypedDict):
    id: str
    dealership_id: str
    unit_id: str
    customer_id: str
    winterized: bool
    daily_rate_cents: int
    start_utc: str
    end_utc: str
    billed_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict):
    id: str
    dealership_id: str
    campaign_code: str
    target_class_type: str
    target_model_year: int
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallRemedy(TypedDict):
    id: str
    dealership_id: str
    recall_campaign_id: str
    unit_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
