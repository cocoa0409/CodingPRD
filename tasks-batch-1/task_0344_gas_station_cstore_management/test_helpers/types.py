"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class TankStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class PumpStatus(str, Enum):
    IDLE = "IDLE"
    DISPENSING = "DISPENSING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"
    REJECTED = "REJECTED"


class ShiftLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    COUNTING = "COUNTING"
    CLOSED = "CLOSED"


class ShiftReconcileStatus(str, Enum):
    PENDING = "PENDING"
    BALANCED = "BALANCED"
    OVER = "OVER"
    SHORT = "SHORT"


class FuelPaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class FuelSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class StoreSettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CarWashStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class FuelGradeCode(str, Enum):
    REGULAR = "REGULAR"
    MIDGRADE = "MIDGRADE"
    PREMIUM = "PREMIUM"
    DIESEL = "DIESEL"


class CarWashPackage(str, Enum):
    BASIC = "BASIC"
    DELUXE = "DELUXE"
    SUPREME = "SUPREME"


class Tender(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class CostBasis(str, Enum):
    WAC = "WAC"
    REPLACEMENT = "REPLACEMENT"


class UserRole(str, Enum):
    STATION_MANAGER = "StationManager"
    CASHIER_ATTENDANT = "CashierAttendant"
    LOYALTY_MEMBER = "LoyaltyMember"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Station(TypedDict):
    id: str
    name: str
    brand: str
    tax_rate_bp: int
    cash_variance_tolerance_cents: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class FuelGrade(TypedDict):
    id: str
    station_id: str
    code: str
    octane: int
    current_price_cents: int
    prior_price_cents: int
    weighted_avg_cost_cents: float
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    station_id: str
    fuel_grade_id: str
    label: str
    capacity_gallons: float
    reorder_point_gallons: float
    volume_gallons: float
    low_stock: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Pump(TypedDict):
    id: str
    station_id: str
    tank_id: str
    number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    station_id: str
    tank_id: str
    vendor_name: str
    net_gallons: float
    unit_cost_cents: int
    invoice_total_cents: int
    paid_cash: bool
    shift_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    station_id: str
    cashier_user_id: str
    opening_float_cents: int
    cash_sales_cents: int
    cash_payouts_cents: int
    cash_drops_cents: int
    expected_drawer_cents: int
    counted_drawer_cents: Optional[int]
    variance_cents: Optional[int]
    lifecycle_status: str
    reconcile_status: str
    created_at: str
    updated_at: str
    version: int


class FuelTransaction(TypedDict):
    id: str
    station_id: str
    pump_id: str
    shift_id: str
    loyalty_account_id: Optional[str]
    gallons: float
    tender: str
    base_price_cents: int
    discount_cents_per_gal: int
    net_price_cents_per_gal: int
    total_cents: int
    cogs_cents: int
    payment_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class StoreTransaction(TypedDict):
    id: str
    station_id: str
    shift_id: str
    loyalty_account_id: Optional[str]
    tender: str
    line_items: list
    verified_buyer_age: Optional[int]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    station_id: str
    phone: str
    name: str
    point_balance: int
    lifetime_points: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class CarWashCode(TypedDict):
    id: str
    station_id: str
    fuel_transaction_id: Optional[str]
    package: str
    price_cents: int
    code_value: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# MarginReport: ephemeral computed snapshot — common_fields: false.
# Carries ONLY id + created_at (no updated_at, no version per PRD §2.4).
class MarginReport(TypedDict):
    id: str
    station_id: str
    window_start: str
    window_end: str
    cost_basis: str
    gallons_sold: float
    revenue_cents: int
    cogs_cents: int
    margin_cents: int
    margin_pct: float
    created_at: str
