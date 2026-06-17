"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the common resource properties described in the
PRD: a server-minted ``id``, a ``created_at`` timestamp, an ``updated_at``
timestamp, and an integer ``version`` that starts at the creation value and
increments on every mutation. All thirteen entity types share these fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    SHOP_MANAGER = "ShopManager"
    DESIGNER = "Designer"
    CUSTOMER = "Customer"
    INSTALLER = "Installer"


# --- Status enums ----------------------------------------------------------
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    QUOTED = "QUOTED"
    CONTRACTED = "CONTRACTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    CHANGE_PENDING = "CHANGE_PENDING"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SpecLockState(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class MaterialReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class MachineStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class BuildJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class FinishCode(str, Enum):
    RAW = "RAW"
    STAIN = "STAIN"
    PAINT = "PAINT"
    LACQUER = "LACQUER"


class Sheen(str, Enum):
    MATTE = "MATTE"
    SATIN = "SATIN"
    GLOSS = "GLOSS"


class DrawType(str, Enum):
    DEPOSIT = "DEPOSIT"
    PROGRESS = "PROGRESS"
    RETAINAGE = "RETAINAGE"


class DrawStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISING = "REVISING"
    CANCELLED = "CANCELLED"


class InstallationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PUNCH_PENDING = "PUNCH_PENDING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class PunchSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


MARGIN_POLICIES = ["STANDARD", "PREMIUM"]


# --- Entity TypedDicts -----------------------------------------------------
# Every entity carries the common fields (id, created_at, updated_at, version).
class Shop(TypedDict):
    id: str
    name: str
    currency: str
    tax_rate_bps: int
    deposit_pct_bps: int
    retainage_pct_bps: int
    rush_surcharge_bps: int
    max_installs_per_day: int
    change_order_buffer_pct_bps: int
    current_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    shop_id: str
    full_name: str
    email: str
    credit_hold: bool
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    shop_id: str
    title: str
    is_rush: bool
    install_address: Optional[str]
    margin_policy: str
    estimate_total_cents: int
    contract_total_cents: int
    deposit_required_cents: int
    billed_to_date_cents: int
    paid_to_date_cents: int
    open_change_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CabinetSpec(TypedDict):
    id: str
    project_id: str
    label: str
    width_mm: int
    height_mm: int
    depth_mm: int
    quantity: int
    base_unit_price_cents: int
    panel_area_mm2: int
    material_id: str
    lock_state: str
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict):
    id: str
    shop_id: str
    sku: str
    sheet_area_mm2: int
    sheet_price_cents: int
    on_hand_sheets: int
    reserved_sheets: int
    available_sheets: int
    created_at: str
    updated_at: str
    version: int


class MaterialReservation(TypedDict):
    id: str
    project_id: str
    material_id: str
    sheets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    shop_id: str
    name: str
    changeover_buffer_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildJob(TypedDict):
    id: str
    project_id: str
    machine_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishSelection(TypedDict):
    id: str
    project_id: str
    finish_code: str
    sheen: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    project_id: str
    draw_type: str
    requested_pct_bps: Optional[int]
    amount_cents: int
    due_utc: Optional[str]
    late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    description: str
    spec_price_delta_cents: int
    delta_cents: int
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict):
    id: str
    project_id: str
    install_date: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict):
    id: str
    installation_id: str
    project_id: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
