"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    CUSTOMER = "Customer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PRESS_OPERATOR = "PressOperator"
    QA_INSPECTOR = "QaInspector"
    PRODUCTION_MANAGER = "ProductionManager"
    WAREHOUSE_MANAGER = "WarehouseManager"
    BILLING_CLERK = "BillingClerk"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DiscountTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class OverrunPolicy(str, Enum):
    EXACT_ONLY = "EXACT_ONLY"
    ACCEPT_AND_BILL_10 = "ACCEPT_AND_BILL_10"
    ACCEPT_ALL_AND_BILL = "ACCEPT_ALL_AND_BILL"


class ReleaseStatus(str, Enum):
    SETUP = "SETUP"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"


class RiskLevel(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    LATE = "LATE"


class ReleaseFormat(str, Enum):
    LP = "LP"
    EP = "EP"
    SINGLE_7 = "SINGLE_7"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    TOOLING = "TOOLING"
    AWAITING_TP_APPROVAL = "AWAITING_TP_APPROVAL"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    PRESSING = "PRESSING"
    QC_REVIEW = "QC_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDIT_CLOSED = "CREDIT_CLOSED"


class ColorConfig(str, Enum):
    BLACK = "BLACK"
    SOLID_COLOR = "SOLID_COLOR"
    SPLATTER = "SPLATTER"
    MARBLED = "MARBLED"
    PICTURE_DISC = "PICTURE_DISC"


class ColorFamily(str, Enum):
    STANDARD = "STANDARD"
    SPECIAL_EFFECT = "SPECIAL_EFFECT"
    PICTURE = "PICTURE"


class PlatingRoute(str, Enum):
    TWO_STEP = "TWO_STEP"
    THREE_STEP = "THREE_STEP"


class Fault(str, Enum):
    NONE = "NONE"
    PLANT = "PLANT"
    CUSTOMER = "CUSTOMER"


class ToolingJobStatus(str, Enum):
    QUEUED = "QUEUED"
    CUTTING = "CUTTING"
    AWAITING_BATH = "AWAITING_BATH"
    PLATING = "PLATING"
    STAMPER_READY = "STAMPER_READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ToolingEvent(str, Enum):
    START_CUT = "START_CUT"
    CUT_DONE = "CUT_DONE"
    START_PLATING = "START_PLATING"
    PLATING_DONE = "PLATING_DONE"
    MARK_FAILED = "MARK_FAILED"


class TestPressingStatus(str, Enum):
    PRODUCED = "PRODUCED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class TpDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class PrintComponent(str, Enum):
    JACKET = "JACKET"
    INNER_SLEEVE = "INNER_SLEEVE"
    INSERT = "INSERT"
    LABEL = "LABEL"


class PrintJobStatus(str, Enum):
    CREATED = "CREATED"
    AT_PRINTER = "AT_PRINTER"
    PROOF_REVIEW = "PROOF_REVIEW"
    PRINTING = "PRINTING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PrintEvent(str, Enum):
    DISPATCH = "DISPATCH"
    PROOFS_IN = "PROOFS_IN"
    DELIVER = "DELIVER"


class ProofDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class TonnageClass(str, Enum):
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"


class SlotKind(str, Enum):
    PRODUCTION = "PRODUCTION"
    MAINTENANCE = "MAINTENANCE"


class ProductionEvent(str, Enum):
    START_PRESSING = "START_PRESSING"
    COMPLETE_PRESSING = "COMPLETE_PRESSING"


class QcOutcome(str, Enum):
    PASS = "PASS"
    HOLD = "HOLD"


class QcReportStatus(str, Enum):
    FILED = "FILED"
    DECIDED = "DECIDED"


class QcDecision(str, Enum):
    NONE = "NONE"
    ACCEPT = "ACCEPT"
    REPRESS = "REPRESS"


class Zone(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class StockEvent(str, Enum):
    RECEIVE = "RECEIVE"
    DAMAGE_WRITE_OFF = "DAMAGE_WRITE_OFF"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    ALLOCATED = "ALLOCATED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class DelayCause(str, Enum):
    TP_REVISION = "TP_REVISION"
    REPRESS = "REPRESS"
    SCHEDULE = "SCHEDULE"
    DATE_REVISION = "DATE_REVISION"


class InvoiceKind(str, Enum):
    STANDARD = "STANDARD"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    CREDIT_MEMO = "CREDIT_MEMO"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDITED = "CREDITED"


class CreditAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Customer(TypedDict):
    id: str
    name: str
    contact_email: str
    credit_limit_cents: int
    discount_tier: str
    overrun_policy: str
    status: str
    trailing_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    customer_id: str
    catalog_number: str
    title: str
    format: str
    weight_gram: int
    release_date: str
    status: str
    risk_level: str
    projected_completion_date: Optional[str]
    slack_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Variant(TypedDict):
    color_config: str
    quantity: int


class PressOrder(TypedDict):
    id: str
    release_id: str
    quantity_ordered: int
    sides: int
    plating_route: str
    overrun_policy: Optional[str]
    variants: List[Variant]
    requested_completion_date: Optional[str]
    production_status: str
    billing_status: str
    discount_pct_snapshot: float
    tolerance_pct: float
    color_family: str
    intake_seq: int
    quote_pressing_cents: int
    quote_surcharge_cents: int
    quote_tooling_cents: int
    quote_setup_cents: int
    quote_subtotal_cents: int
    quote_discount_cents: int
    quote_total_cents: int
    tp_round: int
    repress_round: int
    repress_fault: str
    pressed_units_total: int
    rejected_units_total: int
    accepted_units: int
    cancel_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ToolingJob(TypedDict):
    id: str
    press_order_id: str
    round_number: int
    status: str
    attempt_count: int
    plating_bath_id: Optional[str]
    plating_start: Optional[int]
    plating_end: Optional[int]
    defect_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestPressing(TypedDict):
    id: str
    press_order_id: str
    round_number: int
    quantity: int
    status: str
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintJob(TypedDict):
    id: str
    press_order_id: str
    component: str
    quantity: int
    printer_name: str
    due_date: str
    proof_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PressLine(TypedDict):
    id: str
    line_code: str
    tonnage_class: str
    hours_per_day: int
    daily_unit_capacity: int
    created_at: str
    updated_at: str
    version: int


class PressSlot(TypedDict):
    id: str
    press_line_id: str
    press_order_id: Optional[str]
    slot_kind: str
    date: str
    start_hour: int
    end_hour: int
    planned_units: int
    color_family: Optional[str]
    freed: bool
    created_at: str
    updated_at: str
    version: int


class PlatingBath(TypedDict):
    id: str
    bath_code: str
    rinse_gap_minutes: int
    created_at: str
    updated_at: str
    version: int


class QCReport(TypedDict):
    id: str
    press_order_id: str
    units_pressed: int
    units_rejected: int
    reject_rate_pct: float
    tolerance_pct_snapshot: float
    outcome: str
    status: str
    decision: str
    fault: str
    filed_by: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    release_id: str
    zone: str
    receipt_seq: int
    on_hand_units: int
    allocated_units: int
    shipped_units_cum: int
    damaged_units_cum: int
    received_units_cum: int
    storage_daily_accrual_cents: int
    storage_monthly_statement_cents: int
    created_at: str
    updated_at: str
    version: int


class ShipmentAllocation(TypedDict):
    lot_id: str
    quantity: int


class Shipment(TypedDict):
    id: str
    release_id: str
    distributor_customer_id: str
    quantity: int
    requested_ship_date: str
    status: str
    allocations: List[ShipmentAllocation]
    created_at: str
    updated_at: str
    version: int


# Append-only event log: id + created_at only (NO updated_at, NO version)
class DelayNotice(TypedDict):
    id: str
    release_id: str
    press_order_id: str
    cause: str
    prior_level: str
    new_level: str
    message: str
    created_at: str


class InvoiceLine(TypedDict):
    label: str
    gross_cents: int
    discount_cents: int
    net_cents: int


class Invoice(TypedDict):
    id: str
    press_order_id: str
    customer_id: str
    parent_invoice_id: Optional[str]
    kind: str
    gross_cents: int
    discount_cents: int
    net_cents: int
    paid_cents: int
    credited_cents: int
    lines: List[InvoiceLine]
    status: str
    created_at: str
    updated_at: str
    version: int
