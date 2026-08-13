"""Domain types: entity TypedDicts, status enums, role enum for the dealership API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DEALERSHIP_ADMIN = "DealershipAdmin"
    SALES_MANAGER = "SalesManager"
    SALES_CONSULTANT = "SalesConsultant"
    SERVICE_MANAGER = "ServiceManager"
    SERVICE_ADVISOR = "ServiceAdvisor"
    PARTS_COUNTER_REP = "PartsCounterRep"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    OEM_CLAIMS_ADJUDICATOR = "OEMClaimsAdjudicator"
    CONTROLLER = "Controller"
    FLEET_CUSTOMER = "FleetCustomer"


class AccountType(str, Enum):
    FLEET = "FLEET"
    RETAIL = "RETAIL"


class FleetTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class VocationGroup(str, Enum):
    STANDARD = "STANDARD"
    SEVERE = "SEVERE"


class OrderStatus(str, Enum):
    SLOT_HELD = "SLOT_HELD"
    COMMITTED = "COMMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class UnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RECONDITIONING = "RECONDITIONING"
    READY = "READY"
    SOLD = "SOLD"
    WHOLESALED = "WHOLESALED"


class UnitKind(str, Enum):
    NEW = "NEW"
    USED = "USED"


class AgingBucket(str, Enum):
    B0_90 = "B0_90"
    B91_180 = "B91_180"
    B181_270 = "B181_270"
    B271_365 = "B271_365"
    OVER_365 = "OVER_365"


class EntryType(str, Enum):
    ADVANCE = "ADVANCE"
    INTEREST_ACCRUAL = "INTEREST_ACCRUAL"
    CURTAILMENT = "CURTAILMENT"
    PAYOFF = "PAYOFF"
    ADJUSTMENT = "ADJUSTMENT"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class ResourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BayType(str, Enum):
    STANDARD = "STANDARD"
    HEAVY_ALIGNMENT = "HEAVY_ALIGNMENT"


class AuthStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class WorkStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class LineType(str, Enum):
    LABOR = "LABOR"
    PART = "PART"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SHORT_PAID = "SHORT_PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"
    CLOSED = "CLOSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class SaleStatus(str, Enum):
    INVOICED = "INVOICED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    FULLY_RETURNED = "FULLY_RETURNED"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---

class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    account_type: str
    fleet_tier: str
    credit_limit_cents: int
    open_ar_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FactoryBuildSlot(TypedDict, total=False):
    id: str
    build_month: str
    vocation_group: str
    capacity: int
    held_count: int
    committed_count: int
    slots_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FactoryOrder(TypedDict, total=False):
    id: str
    customer_account_id: Optional[str]
    factory_build_slot_id: str
    chassis_model: str
    engine_option: str
    axle_config: str
    vocation_group: str
    upfit_lines: List[dict]
    hold_expires_at: str
    provisional_total_cents: int
    committed_total_cents: int
    received_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    vin: str
    unit_kind: str
    factory_order_id: Optional[str]
    trade_appraisal_id: Optional[str]
    status: str
    invoice_cost_cents: int
    stocking_date: str
    days_in_stock: int
    aging_bucket: str
    floorplan_active: bool
    apr_bp: int
    floorplan_balance_cents: int
    last_accrual_date: Optional[str]
    curtailment_due_cents: int
    recondition_count: int
    sold_price_cents: Optional[int]
    sold_at: Optional[str]
    wholesale_price_cents: Optional[int]
    wholesale_loss_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger line: id + created_at only (NO updated_at, NO version).
class FloorPlanEntry(TypedDict, total=False):
    id: str
    unit_id: str
    entry_type: str
    amount_cents: int
    entry_date: str
    note: Optional[str]
    resulting_balance_cents: int
    created_at: str


class TradeAppraisal(TypedDict, total=False):
    id: str
    customer_account_id: str
    trade_vin: str
    model_year: int
    mileage: int
    condition_grade: str
    base_book_value_cents: int
    book_estimate_cents: int
    market_index_bp: Optional[int]
    offer_acv_cents: Optional[int]
    offered_allowance_cents: Optional[int]
    offer_expires_at: Optional[str]
    offer_round: int
    created_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict, total=False):
    id: str
    bay_code: str
    bay_type: str
    open_hour: int
    close_hour: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MobileServiceUnit(TypedDict, total=False):
    id: str
    unit_code: str
    default_travel_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    customer_account_id: str
    unit_id: Optional[str]
    external_vin: Optional[str]
    concern: str
    promised_ready_at: str
    labor_rate_cents: int
    auth_status: str
    work_status: str
    labor_sum_cents: int
    parts_sum_cents: int
    discount_cents: int
    shop_supplies_fee_cents: int
    warranty_covered_cents: int
    customer_due_cents: int
    downtime_penalty_cents: int
    work_started_at: Optional[str]
    completed_at: Optional[str]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class RepairOrderLine(TypedDict, total=False):
    id: str
    repair_order_id: str
    line_type: str
    part_id: Optional[str]
    description: Optional[str]
    hours: Optional[float]
    quantity: Optional[int]
    unit_price_cents: int
    line_total_cents: int
    warranty_eligible: bool
    created_at: str
    updated_at: str
    version: int


class ServiceBooking(TypedDict, total=False):
    id: str
    repair_order_id: str
    service_bay_id: Optional[str]
    mobile_service_unit_id: Optional[str]
    start_at: str
    end_at: str
    travel_minutes: int
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    repair_order_id: str
    claimed_labor_cents: int
    claimed_parts_cents: int
    approved_labor_cents: Optional[int]
    approved_parts_cents: Optional[int]
    paid_cents: int
    submitted_by_user_id: str
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    denial_reason: Optional[str]
    appeal_notes: Optional[str]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    part_name: str
    list_price_cents: int
    cost_cents: int
    on_hand: int
    has_core_charge: bool
    core_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsSale(TypedDict, total=False):
    id: str
    customer_account_id: str
    lines: List[dict]
    subtotal_cents: int
    core_total_cents: int
    total_cents: int
    sold_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsSaleLine(TypedDict, total=False):
    id: str
    parts_sale_id: str
    part_id: str
    quantity: int
    unit_net_price_cents: int
    line_total_cents: int
    returned_quantity: int
    return_credit_cents: int
    created_at: str
    updated_at: str
    version: int
