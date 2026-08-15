"""Domain types: entity TypedDicts, status enums, role enum.

Entities with full bookkeeping carry id + created_at + updated_at + version.
Ledger-style records (weigh events, drops, reconciliations, safe deposits,
deliveries, points lots) carry only id + created_at per PRD section 2.4.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    GENERAL_MANAGER = "GeneralManager"
    SHIFT_MANAGER = "ShiftManager"
    FUEL_DESK_LEAD = "FuelDeskLead"
    CASHIER = "Cashier"
    MAINTENANCE_TECH = "MaintenanceTech"
    FLEET_MANAGER = "FleetManager"
    LOYALTY_MEMBER = "LoyaltyMember"


class FuelType(str, Enum):
    DIESEL = "DIESEL"
    GAS_REGULAR = "GAS_REGULAR"
    GAS_PREMIUM = "GAS_PREMIUM"
    DEF = "DEF"


class PricingTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class NetworkStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"
    CANCELLED = "CANCELLED"


class FuelPriceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PumpStatus(str, Enum):
    IDLE = "IDLE"
    IN_USE = "IN_USE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FuelSaleStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    FUELING = "FUELING"
    PENDING_FINALIZE = "PENDING_FINALIZE"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    BILLED = "BILLED"
    REFUNDED = "REFUNDED"


class TenderType(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    FLEET_BILLING = "FLEET_BILLING"


class PricingMode(str, Enum):
    RETAIL = "RETAIL"
    CONTRACT = "CONTRACT"


class SpaceType(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZED = "OVERSIZED"


class ParkingSpaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ReservationPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ServiceType(str, Enum):
    SHOWER = "SHOWER"
    LAUNDRY = "LAUNDRY"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    CALLED = "CALLED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ScaleTicketStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class WeighKind(str, Enum):
    GROSS = "GROSS"
    TARE = "TARE"
    REWEIGH = "REWEIGH"


class StockCategory(str, Enum):
    RESTAURANT = "RESTAURANT"
    RETAIL = "RETAIL"
    SHOP_PART = "SHOP_PART"
    PACKAGED_OIL = "PACKAGED_OIL"


class VendorCategory(str, Enum):
    FUEL = "FUEL"
    DEF_OIL = "DEF_OIL"
    FOOD = "FOOD"
    GENERAL = "GENERAL"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class BayStatus(str, Enum):
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"


class WorkOrderStatus(str, Enum):
    CREATED = "CREATED"
    ESTIMATED = "ESTIMATED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_SHOP = "IN_SHOP"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_VENDOR = "WAITING_VENDOR"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WorkOrderPartStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"


class RegisterPosture(str, Enum):
    OK = "OK"
    NEEDS_DROP = "NEEDS_DROP"
    LOW_FLOAT = "LOW_FLOAT"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"
    LOCKED = "LOCKED"


class ShiftLabel(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    GRAVEYARD = "GRAVEYARD"


class ReconciliationResolution(str, Enum):
    BALANCED = "BALANCED"
    OVERAGE = "OVERAGE"
    SHORTAGE = "SHORTAGE"


class ProductType(str, Enum):
    DIESEL = "DIESEL"
    DEF = "DEF"
    OIL = "OIL"


class StoreSaleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class StoreSalePaymentStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PointsSourceType(str, Enum):
    FUEL_SALE = "FUEL_SALE"
    STORE_SALE = "STORE_SALE"
    SERVICE = "SERVICE"
    PARKING = "PARKING"
    ADJUSTMENT = "ADJUSTMENT"


# ---------------------------------------------------------------------------
# Entity records (full bookkeeping: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------


class TravelCenterSite(TypedDict, total=False):
    id: str
    name: str
    parking_total_spaces: int
    parking_paid_capacity: int
    shower_units_count: int
    laundry_machines_count: int
    diesel_retail_cents_per_gallon: Optional[int]
    gas_regular_retail_cents_per_gallon: Optional[int]
    def_retail_cents_per_gallon: Optional[int]
    water_usage_gallons: float
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    current_balance_cents: int
    pricing_tier: str
    rolling_30d_gallons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetContract(TypedDict, total=False):
    id: str
    fleet_account_id: str
    contract_code: str
    pricing_tier: str
    discount_per_gallon_off: float
    applicable_fuel_types: List[str]
    effective_from: str
    effective_to: str
    status: str
    volume_delivered_gallons: float
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    fleet_account_id: Optional[str]
    stack_cap_points: int
    points_balance: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegisteredVehicle(TypedDict, total=False):
    id: str
    loyalty_member_id: str
    plate: str
    vehicle_type: str
    created_at: str
    updated_at: str
    version: int


class DiscountNetworkProgram(TypedDict, total=False):
    id: str
    name: str
    discount_per_gallon: float
    applicable_fuel_types: List[str]
    program_cap: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscountNetworkEnrollment(TypedDict, total=False):
    id: str
    network_program_id: str
    loyalty_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelPrice(TypedDict, total=False):
    id: str
    site_id: str
    fuel_type: str
    retail_cents_per_gallon: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pump(TypedDict, total=False):
    id: str
    site_id: str
    pump_number: int
    fuel_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelSale(TypedDict, total=False):
    id: str
    site_id: str
    pump_id: str
    shift_id: str
    loyalty_member_id: Optional[str]
    fleet_account_id: Optional[str]
    contract_id: Optional[str]
    pricing_mode: str
    fuel_type: str
    tender_type: str
    status: str
    payment_status: str
    max_gallons: float
    requested_redeem_points: int
    retail_price_snapshot: Optional[int]
    network_discount_snapshot: float
    contract_discount_snapshot: Optional[float]
    contract_rate_snapshot_cents: Optional[int]
    points_redeemed: int
    points_discount_cents: int
    stack_cap_snapshot: Optional[int]
    authorized_quote_cents_per_gallon: int
    provisional_fuel_total_cents: int
    dispensed_gallons: Optional[float]
    final_unit_price_cents: Optional[int]
    fuel_amount_cents: Optional[int]
    total_cents: Optional[int]
    tax_cents: int
    points_earned: int
    finalized_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParkingSpace(TypedDict, total=False):
    id: str
    site_id: str
    space_number: str
    space_type: str
    is_reservable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ParkingReservation(TypedDict, total=False):
    id: str
    site_id: str
    loyalty_member_id: str
    vehicle_plate: str
    space_type: str
    reserved_from: str
    reserved_to: str
    requested_redeem_points: int
    status: str
    payment_status: str
    paid_minutes: int
    billed_hours: int
    oversize_fee_cents: int
    points_discount_cents: int
    amount_cents: int
    assigned_space_id: Optional[str]
    shift_id: Optional[str]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceQueueTicket(TypedDict, total=False):
    id: str
    site_id: str
    shift_id: Optional[str]
    loyalty_member_id: Optional[str]
    service_type: str
    requested_redeem_points: int
    status: str
    payment_status: str
    queue_position: int
    base_price_cents: int
    weekend_surcharge_cents: int
    peak_surcharge_cents: int
    points_discount_cents: int
    total_price_cents: int
    called_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    shower_minutes: Optional[int]
    laundry_lbs: Optional[float]
    water_gallons: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict, total=False):
    id: str
    site_id: str
    shift_id: str
    vehicle_plate: str
    carrier_name: str
    certified: bool
    status: str
    reweigh_count: int
    gross_lbs: Optional[int]
    tare_lbs: Optional[int]
    net_lbs: Optional[int]
    total_paid_cents: int
    refund_total_cents: int
    created_at: str
    updated_at: str
    version: int


class StockItem(TypedDict, total=False):
    id: str
    site_id: str
    sku: str
    name: str
    category: str
    unit: str
    unit_price_cents: int
    on_hand_quantity: int
    reorder_point: int
    is_low_stock: bool
    vendor_id: Optional[str]
    case_pack_gallons: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    category: str
    created_at: str
    updated_at: str
    version: int


class VendorPrice(TypedDict, total=False):
    id: str
    vendor_id: str
    item_sku: str
    unit: str
    unit_price_cents: int
    pack_size: int
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    site_id: str
    vendor_id: str
    lines: List[Dict[str, Any]]
    status: str
    total_cents: int
    received_lines: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    hourly_rate_cents: int
    certifications: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopBay(TypedDict, total=False):
    id: str
    site_id: str
    bay_number: int
    status: str
    maintenance_blocks: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    site_id: str
    vehicle_plate: str
    complaint: str
    fleet_account_id: Optional[str]
    technician_id: Optional[str]
    bay_id: Optional[str]
    scheduled_from: Optional[str]
    scheduled_to: Optional[str]
    status: str
    is_road_service: bool
    road_location_text: Optional[str]
    labor_hours_est: Optional[float]
    labor_hours_actual: Optional[float]
    parts_total_cents: Optional[int]
    labor_total_cents: Optional[int]
    environmental_fee_cents: Optional[int]
    shop_supplies_cents: Optional[int]
    invoice_total_cents: Optional[int]
    payment_status: str
    vendor_out_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrderPart(TypedDict, total=False):
    id: str
    work_order_id: str
    stock_item_id: str
    quantity: int
    returned_quantity: int
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Register(TypedDict, total=False):
    id: str
    site_id: str
    register_code: str
    float_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    site_id: str
    register_id: str
    cashier_user_id: str
    shift_label: str
    opened_by_manager_id: str
    closed_by_manager_id: Optional[str]
    status: str
    opening_float_cents: int
    expected_cash_cents: int
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoreSale(TypedDict, total=False):
    id: str
    site_id: str
    shift_id: str
    loyalty_member_id: Optional[str]
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    total_cents: int
    tender_type: str
    status: str
    payment_status: str
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class BulkTank(TypedDict, total=False):
    id: str
    site_id: str
    product_type: str
    capacity_gallons: float
    current_gallons: float
    reorder_threshold_gallons: float
    safety_stock_gallons: float
    daily_usage_gallons: float
    lead_time_days: int
    rack_price_cents_per_gallon_4dp: Optional[float]
    is_low_stock: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Ledger-style records (id + created_at only; no updated_at, no version)
# ---------------------------------------------------------------------------


class ScaleWeighEvent(TypedDict, total=False):
    id: str
    scale_ticket_id: str
    weigh_kind: str
    weight_lbs: int
    sequence: int
    created_at: str


class CashDrop(TypedDict, total=False):
    id: str
    shift_id: str
    register_id: str
    amount_cents: int
    denominations: Dict[str, int]
    status: str
    created_at: str


class ShiftReconciliation(TypedDict, total=False):
    id: str
    shift_id: str
    expected_cash_cents: int
    counted_cash_cents: int
    variance_cents: int
    resolution: str
    deposit_total_cents: int
    created_at: str


class SafeDeposit(TypedDict, total=False):
    id: str
    shift_id: str
    register_id: str
    amount_cents: int
    status: str
    created_at: str


class BulkDelivery(TypedDict, total=False):
    id: str
    bulk_tank_id: str
    vendor_id: Optional[str]
    gallons_delivered: float
    water_bottom_inches: float
    rack_price_cents_per_gallon_4dp: Optional[float]
    status: str
    created_at: str


class LoyaltyPointsLot(TypedDict, total=False):
    id: str
    loyalty_member_id: str
    points: int
    remaining_points: int
    source_type: str
    source_id: str
    earned_at: str
    expires_at: str
    created_at: str
