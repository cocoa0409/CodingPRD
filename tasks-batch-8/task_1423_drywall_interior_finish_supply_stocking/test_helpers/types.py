"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CREDIT_MANAGER = "CreditManager"
    ESTIMATOR = "EstimatorUser"
    DISPATCHER = "DispatcherUser"
    FOREMAN = "Foreman"
    CONTRACTOR_ADMIN = "ContractorAdmin"
    ACCOUNTS_RECEIVABLE = "AccountsReceivableUser"
    WAREHOUSE_MANAGER = "WarehouseManager"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BoardKind(str, Enum):
    REGULAR = "REGULAR"
    FIRE_RATED = "FIRE_RATED"
    MOISTURE_RATED = "MOISTURE_RATED"


class ThicknessIn(str, Enum):
    HALF = "1/2"
    FIVE_EIGHTH = "5/8"
    THREE_QUARTER = "3/4"


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    STOCKING_OPEN = "STOCKING_OPEN"
    STOCKING_CLOSED = "STOCKING_CLOSED"
    CANCELLED = "CANCELLED"


class TakeoffStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class StockingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    STOCKED = "STOCKED"
    CANCELLED = "CANCELLED"


class ShiftWindow(str, Enum):
    AM = "AM"
    PM = "PM"


class DrawStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    CARD = "CARD"


class ReturnStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ContractorAccount(TypedDict, total=False):
    id: str
    company_name: str
    credit_limit_cents: int
    default_waste_pct_bp: int
    ar_outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    board_kind: str
    length_ft: int
    width_ft: int
    thickness_in: str
    sheets_per_bundle: int
    unit_price_cents_per_sheet: int
    lead_time_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    account_id: str
    jobsite_name: str
    distance_miles: int
    framing_pct_complete: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Takeoff(TypedDict, total=False):
    id: str
    project_id: str
    waste_pct_bp_override: Optional[int]
    base_sheet_count: int
    billable_sheet_count: int
    quoted_subtotal_cents: int
    final_subtotal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TakeoffLine(TypedDict, total=False):
    id: str
    takeoff_id: str
    product_id: str
    sheet_count: int
    waste_sheets: int
    bundle_count: int
    quoted_line_cents: int
    final_line_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class StockingOrder(TypedDict, total=False):
    id: str
    project_id: str
    takeoff_id: str
    scheduled_date: str
    shift_window: str
    boom_truck_id: str
    freight_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StockingDrop(TypedDict, total=False):
    id: str
    stocking_order_id: str
    floor_label: str
    room_label: str
    product_id: str
    bundle_count: int
    sheet_weight_lbs: int
    created_at: str
    updated_at: str
    version: int


class BoomTruck(TypedDict, total=False):
    id: str
    truck_code: str
    max_bundle_capacity: int
    max_weight_lbs: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict, total=False):
    id: str
    project_id: str
    stocking_order_id: str
    requested_cents: int
    status: str
    paid_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (PRD §2.4): carries ONLY id + created_at,
# NO updated_at, NO version.
class Payment(TypedDict, total=False):
    id: str
    draw_request_id: str
    amount_cents: int
    method: str
    received_at: str
    created_at: str


class BundleReturn(TypedDict, total=False):
    id: str
    stocking_order_id: str
    product_id: str
    bundles_returned: int
    loose_sheets_returned: int
    restock_fee_cents: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
