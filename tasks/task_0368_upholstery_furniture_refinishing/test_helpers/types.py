"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_CLERK = "IntakeClerk"
    ESTIMATOR = "Estimator"
    SHOP_MANAGER = "ShopManager"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class WorkOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    ESTIMATING = "ESTIMATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_FOR_FULFILLMENT = "READY_FOR_FULFILLMENT"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class FabricSkuStatus(str, Enum):
    LISTED = "LISTED"
    DISCONTINUED = "DISCONTINUED"


class FoamSpecStatus(str, Enum):
    LISTED = "LISTED"
    DISCONTINUED = "DISCONTINUED"


class EstimateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class MaterialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ShopDayStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class FulfillmentLegKind(str, Enum):
    PRODUCTION = "PRODUCTION"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class FulfillmentLegStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ServiceType(str, Enum):
    REUPHOLSTERY = "REUPHOLSTERY"
    REFINISH = "REFINISH"
    REPAIR = "REPAIR"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    SETTLEMENT = "SETTLEMENT"
    REFUND = "REFUND"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    WALLET = "WALLET"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true entities carry id, created_at, updated_at, version.
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class FabricSku(TypedDict):
    id: str
    sku_code: str
    name: str
    price_cents_per_yard: int
    roll_width_inches: int
    in_stock_yards: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FoamSpec(TypedDict):
    id: str
    grade_code: str
    density_lb: float
    price_cents_per_board_foot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    customer_id: str
    service_type: str
    rush_requested: bool
    promised_turnaround_days: Optional[int]
    estimate_total_cents: int
    final_invoice_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    materials_committed_cents: int
    status: str
    active_estimate_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    work_order_id: str
    piece_label: str
    fabric_sku_id: Optional[str]
    foam_spec_id: Optional[str]
    yardage_required: float
    board_feet_required: float
    labor_hours: float
    piece_subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    work_order_id: str
    supersedes_estimate_id: Optional[str]
    version_no: int
    labor_total_cents: int
    materials_total_cents: int
    rush_surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    work_order_id: str
    fabric_sku_id: Optional[str]
    foam_spec_id: Optional[str]
    yards_ordered: float
    board_feet_ordered: float
    provisional_cost_cents: int
    finalized_cost_cents: int
    received_fabric_price_cents_per_yard: int
    received_foam_price_cents_per_board_foot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopDay(TypedDict):
    id: str
    work_date: str
    labor_capacity_hours: float
    booked_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentLeg(TypedDict):
    id: str
    work_order_id: str
    shop_day_id: Optional[str]
    kind: str
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    work_order_id: str
    defect_note: str
    filed_at: str
    covered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    work_order_id: str
    kind: str
    amount_cents: int
    refund_destination: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — ConditionPhoto is immutable: id + created_at only.
class ConditionPhoto(TypedDict):
    id: str
    work_order_id: str
    image_uri: str
    damage_note: str
    sequence_no: int
    created_at: str
