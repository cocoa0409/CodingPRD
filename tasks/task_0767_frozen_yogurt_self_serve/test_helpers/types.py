"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ------------------------------------------------------------------
class UserRole(str, Enum):
    CASHIER = "Cashier"
    SHIFT_LEAD = "ShiftLead"
    MANAGER = "Manager"


# --- Status enums -----------------------------------------------------------
class MachineStatus(str, Enum):
    READY = "READY"
    CLEANING = "CLEANING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FlavorStatus(str, Enum):
    LOADED = "LOADED"
    SUSPENDED = "SUSPENDED"
    ROTATED_OUT = "ROTATED_OUT"


class ToppingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ROTATED_OUT = "ROTATED_OUT"


class LoyaltyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, Enum):
    OPEN = "OPEN"
    CHARGED = "CHARGED"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    RECONCILED = "RECONCILED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class CateringStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ReconStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WasteReason(str, Enum):
    MELT = "MELT"
    SPILL = "SPILL"
    EXPIRY = "EXPIRY"
    MACHINE_FAULT = "MACHINE_FAULT"


# Allowed allergen codes.
ALLERGENS = ["DAIRY", "NUTS", "SOY", "GLUTEN", "EGG"]


# --- Fully-versioned entities (id + created_at + updated_at + version) -------
class Machine(TypedDict):
    id: str
    name: str
    mix_par_oz: float
    current_mix_level_oz: float
    last_cleaned_at: str
    next_maintenance_at: Optional[str]
    sanitation_status: str
    created_at: str
    updated_at: str
    version: int


class Flavor(TypedDict):
    id: str
    machine_id: str
    name: str
    price_per_oz_cents: int
    cost_per_oz_cents: int
    allergen_tags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Topping(TypedDict):
    id: str
    name: str
    surcharge_cents: int
    on_hand_units: int
    allergen_tags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalPromotion(TypedDict):
    id: str
    name: str
    discount_pct: float
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    member_name: str
    phone: Optional[str]
    points_provisional: int
    points_lifetime: int
    punch_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RewardVoucher(TypedDict):
    id: str
    loyalty_account_id: str
    value_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleTicket(TypedDict):
    id: str
    loyalty_account_id: Optional[str]
    excluded_allergens: List[str]
    reconciliation_id: Optional[str]
    redeemed_voucher_id: Optional[str]
    quoted_total_cents: int
    final_total_cents: Optional[int]
    provisional_points: int
    final_points: Optional[int]
    payment_status: str
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    machine_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringResource(TypedDict):
    id: str
    name: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict):
    id: str
    resource_id: str
    loyalty_account_id: Optional[str]
    event_start: str
    event_end: str
    guest_count: int
    line_items: List[dict]
    invoice_total_cents: Optional[int]
    required_deposit_cents: Optional[int]
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReconciliation(TypedDict):
    id: str
    business_date: str
    counted_cash_cents: Optional[int]
    expected_revenue_cents: Optional[int]
    cash_variance_cents: Optional[int]
    adjustments: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only / immutable entities (id + created_at ONLY) ----------------
class SaleLine(TypedDict):
    id: str
    ticket_id: str
    flavor_id: str
    gross_weight_oz: float
    container_tare_oz: float
    net_weight_oz: float
    topping_ids: List[str]
    line_quoted_cents: int
    created_at: str


class WasteEvent(TypedDict):
    id: str
    machine_id: Optional[str]
    flavor_id: Optional[str]
    topping_id: Optional[str]
    waste_weight_oz: Optional[float]
    waste_units: Optional[int]
    reason: str
    cogs_value_cents: int
    retail_value_cents: int
    created_at: str


class SanitationLog(TypedDict):
    id: str
    machine_id: str
    cleaned_at: str
    previous_status: str
    created_at: str
