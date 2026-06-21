"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    FRAME_DESIGNER = "FrameDesigner"
    FRAME_PRODUCTION_TECH = "FrameProductionTech"
    FRONT_DESK_CLERK = "FrontDeskClerk"
    CUSTOMER = "Customer"


# --- Status enums ---
class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    TRADE = "TRADE"


class ProductionStatus(str, Enum):
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class LineStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    VOID = "VOID"


class TaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class BenchType(str, Enum):
    ASSEMBLY = "ASSEMBLY"
    GLASS_CUTTING = "GLASS_CUTTING"


class GlassType(str, Enum):
    REGULAR = "REGULAR"
    CONSERVATION = "CONSERVATION"
    MUSEUM = "MUSEUM"


class MountingType(str, Enum):
    NONE = "NONE"
    PLAIN = "PLAIN"
    DRY_MOUNT = "DRY_MOUNT"
    CONSERVATION_HINGE = "CONSERVATION_HINGE"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class NotificationKind(str, Enum):
    READY = "READY"
    DEPOSIT_RECEIPT = "DEPOSIT_RECEIPT"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    loyalty_tier: str
    loyalty_discount_pct: float
    open_order_count: int
    no_show_risk_score: int
    settled_reputation_score: int
    created_at: str
    updated_at: str
    version: int


class Workbench(TypedDict):
    id: str
    bench_name: str
    bench_type: str
    clean_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class FramingOrder(TypedDict):
    id: str
    customer_id: str
    reorder_of_order_id: Optional[str]
    rush_requested: bool
    deposit_pct: float
    production_status: str
    payment_status: str
    has_fragile_line: bool
    estimate_total: float
    deposit_required: float
    final_invoice_total: float
    amount_paid: float
    balance_due: float
    turnaround_days: int
    created_at: str
    updated_at: str
    version: int


class FrameLine(TypedDict):
    id: str
    order_id: str
    artwork_label: str
    nominal_width_in: float
    nominal_height_in: float
    measured_width_in: Optional[float]
    measured_height_in: Optional[float]
    mat_border_in: float
    mat_layers: int
    glass_type: str
    molding_rate_per_ui: float
    mounting_type: str
    conservation_package: bool
    is_fragile: bool
    line_status: str
    estimate_subtotal: float
    final_subtotal: float
    created_at: str
    updated_at: str
    version: int


class ProductionTask(TypedDict):
    id: str
    order_id: str
    workbench_id: str
    start_minute: int
    end_minute: int
    task_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    order_id: str
    kind: str
    amount: float
    payment_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, only id + created_at (NO updated_at, NO version)
class Notification(TypedDict):
    id: str
    order_id: str
    channel: str
    kind: str
    sent_to: str
    created_at: str
