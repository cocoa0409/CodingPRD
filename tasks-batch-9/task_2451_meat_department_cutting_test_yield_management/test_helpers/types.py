"""Domain types for the Meat Department Yield Management API.

Entity TypedDicts, state enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STORE_ADMIN = "StoreAdmin"
    MEAT_CUTTER = "MeatCutter"
    MEAT_MANAGER = "MeatManager"
    PRICING_ANALYST = "PricingAnalyst"
    SERVICE_CLERK = "ServiceClerk"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CasePosture(str, Enum):
    SALES_OPEN = "SALES_OPEN"
    SALES_RESTRICTED = "SALES_RESTRICTED"
    SALES_HALTED = "SALES_HALTED"


class PrimalCode(str, Enum):
    BEEF_RIBEYE_LIP_ON = "BEEF_RIBEYE_LIP_ON"
    BEEF_STRIP_LOIN = "BEEF_STRIP_LOIN"
    PORK_LOIN_BONELESS = "PORK_LOIN_BONELESS"
    BEEF_CHUCK_ROLL = "BEEF_CHUCK_ROLL"


class CountryOfOrigin(str, Enum):
    USA = "USA"
    CAN = "CAN"
    MEX = "MEX"
    AUS = "AUS"


class CooLabel(str, Enum):
    PENDING = "PENDING"
    USA = "USA"
    CAN = "CAN"
    MEX = "MEX"
    AUS = "AUS"
    MULTIPLE = "MULTIPLE"


class ProductClass(str, Enum):
    GROUND = "GROUND"
    WHOLE_MUSCLE = "WHOLE_MUSCLE"
    VAC_PACKED = "VAC_PACKED"


class PurchaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CUT_TESTED = "CUT_TESTED"
    RECONCILED = "RECONCILED"


class CuttingTestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CuttingTestAction(str, Enum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVISE = "REVISE"


class Disposition(str, Enum):
    SALABLE_CUT = "SALABLE_CUT"
    GRIND_TRIM = "GRIND_TRIM"
    FAT_BONE_LOSS = "FAT_BONE_LOSS"


class PriceStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PROPOSED = "PROPOSED"
    PRICED = "PRICED"
    REPRICE_REQUIRED = "REPRICE_REQUIRED"
    SUSPENDED = "SUSPENDED"


class RetailItemAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class CostBasisSource(str, Enum):
    CUT_TEST_LINE = "CUT_TEST_LINE"
    GRIND_BLEND = "GRIND_BLEND"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class FillStatus(str, Enum):
    UNFILLED = "UNFILLED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"


class CasePlanAction(str, Enum):
    PUBLISH = "PUBLISH"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    CLOSE = "CLOSE"


class LineStatus(str, Enum):
    PLANNED = "PLANNED"
    FILLED = "FILLED"
    MARKED_DOWN = "MARKED_DOWN"
    HELD = "HELD"
    SHRUNK_OUT = "SHRUNK_OUT"


class TrimLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"


class TrimLotAction(str, Enum):
    DISCARD = "DISCARD"


class GrindRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class GrindRunAction(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"
    ABORT = "ABORT"


class CaseFailureStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class CaseFailureAction(str, Enum):
    CONTAIN = "CONTAIN"
    ESCALATE = "ESCALATE"
    RESOLVE = "RESOLVE"


class CaseFailureDisposition(str, Enum):
    NONE = "NONE"
    MARKDOWN = "MARKDOWN"
    DISCARD = "DISCARD"


class PreOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    STAGED = "STAGED"
    HELD = "HELD"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"
    FORFEITED = "FORFEITED"


class PreOrderAction(str, Enum):
    CONFIRM = "CONFIRM"
    AMEND = "AMEND"
    STAGE = "STAGE"
    PICK_UP = "PICK_UP"
    CANCEL = "CANCEL"
    FORFEIT = "FORFEIT"


class ReconciliationBasis(str, Enum):
    YIELD_MODEL = "YIELD_MODEL"
    PHYSICAL_COUNT = "PHYSICAL_COUNT"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"


class ReconciliationAction(str, Enum):
    POST = "POST"
    DISPUTE = "DISPUTE"
    REDRAFT = "REDRAFT"


# ---------------------------------------------------------------------------
# Entity shapes (PRD §2.4 common fields plus the per-entity fields of §3)
# ---------------------------------------------------------------------------

class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Department(CommonFields):
    name: str
    store_code: str
    target_margin_pct: float
    shelf_life_days_ground: int
    shelf_life_days_whole_muscle: int
    shelf_life_days_vac_packed: int
    max_safe_case_temp_c: float
    critical_case_temp_c: float
    pickup_slot_capacity: int
    grind_sanitation_buffer_min: int
    markdown_floor_pct: float
    shrink_tolerance_pct: float
    deposit_rate: float
    case_posture: str
    open_case_failure_count: int
    contained_case_failure_count: int
    consecutive_out_of_spec_readings: int


class PrimalPurchase(CommonFields):
    department_id: str
    primal_code: str
    product_class: str
    country_of_origin: str
    vendor_name: str
    gross_weight_lb: float
    invoice_cost_cents: int
    freight_cost_cents: int
    vendor_allowance_cents: int
    receiving_shrink_lb: float
    received_at: str
    net_weight_lb: float
    landed_cost_total_cents: int
    landed_cost_per_lb_cents: float
    allocated_cost_cents: int
    unallocated_cost_cents: int
    status: str


class CuttingTest(CommonFields):
    primal_purchase_id: str
    test_weight_lb: float
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    revision_count: int
    total_yield_weight_lb: float
    unaccounted_lb: float
    salable_yield_pct: float
    trim_yield_pct: float
    loss_pct: float
    status: str


class CuttingTestLine(CommonFields):
    cutting_test_id: str
    retail_item_id: Optional[str]
    line_seq: int
    subprimal_code: str
    disposition: str
    yield_weight_lb: float
    market_value_per_lb_cents: int
    lean_pct: Optional[float]
    allocated_cost_cents: int
    allocated_cost_per_lb_cents: float


class RetailItem(CommonFields):
    department_id: str
    item_code: str
    subprimal_code: str
    product_class: str
    country_of_origin_label: str
    target_margin_pct: Optional[float]
    cost_basis_source: str
    pricing_yield_pct_snapshot: float
    yield_adjusted_cost_per_lb_cents: float
    provisional_price_per_lb_cents: int
    final_price_per_lb_cents: int
    active_price_per_lb_cents: int
    price_variance_pct: float
    shelf_life_days: int
    price_status: str


class CasePlan(CommonFields):
    department_id: str
    service_date: str
    published_by_user_id: Optional[str]
    total_expected_movement_lb: float
    total_required_fill_lb: float
    total_actual_fill_lb: float
    price_stale_line_count: int
    plan_status: str
    fill_status: str


class CasePlanLine(CommonFields):
    case_plan_id: str
    retail_item_id: str
    line_seq: int
    facings: int
    expected_movement_lb: float
    required_fill_lb: float
    actual_fill_lb: float
    staged_lb: float
    pack_date: Optional[str]
    sell_by_date: Optional[str]
    markdown_lb: float
    markdown_price_per_lb_cents: int
    markdown_dollars_cents: int
    shrink_lb: float
    price_stale: bool
    held_from_status: Optional[str]
    line_status: str


class TrimLot(CommonFields):
    department_id: str
    cutting_test_line_id: Optional[str]
    source_trim_lot_id: Optional[str]
    lot_code: str
    received_lb: float
    pack_date: str
    country_of_origin: Optional[str]
    lean_pct: Optional[float]
    cost_per_lb_cents: float
    rework_generation: int
    allocated_lb: float
    consumed_lb: float
    discarded_lb: float
    remaining_lb: float
    sell_by_date: Optional[str]
    status: str


class GrindRun(CommonFields):
    department_id: str
    target_retail_item_id: str
    fill_case_plan_line_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    declared_coo: str
    target_lean_pct: float
    lean_tolerance_pct: float
    batch_weight_lb: float
    blended_lean_pct: float
    blend_cost_per_lb_cents: float
    coo_label: str
    started_by_user_id: Optional[str]
    abort_reason: Optional[str]
    completed_at: Optional[str]
    status: str


class GrindInput(CommonFields):
    grind_run_id: str
    trim_lot_id: str
    input_seq: int
    weight_lb: float
    consumed: bool


class TemperatureLog(TypedDict):
    """PRD §2.4: a temperature log carries only `id` and `created_at` — it has
    no `updated_at` and no `version`."""

    id: str
    created_at: str
    department_id: str
    case_code: str
    reading_c: float
    taken_at: str
    recorded_by_user_id: str
    out_of_spec: bool
    consecutive_index: int


class CaseFailure(CommonFields):
    department_id: str
    trigger_temperature_log_id: str
    case_code: str
    opened_at: str
    reported_by_user_id: str
    peak_reading_c: float
    reopen_count: int
    containment_note: Optional[str]
    disposition: str
    affected_line_count: int
    contained_at: Optional[str]
    escalated_at: Optional[str]
    resolved_at: Optional[str]
    resolved_by_user_id: Optional[str]
    status: str


class PreOrder(CommonFields):
    department_id: str
    retail_item_id: str
    staged_case_plan_line_id: Optional[str]
    customer_name: str
    customer_phone: str
    requested_weight_lb: float
    pickup_window_start_at: str
    pickup_window_end_at: str
    quoted_price_per_lb_cents: int
    pinned_retail_item_version: int
    deposit_cents: int
    deposit_applied_cents: int
    deposit_refund_cents: int
    deposit_forfeited_cents: int
    amend_count: int
    status: str


class ShrinkReconciliation(CommonFields):
    department_id: str
    period_start_date: str
    period_end_date: str
    basis: str
    expected_salable_lb: float
    physical_salable_lb: float
    variance_lb: float
    variance_pct: float
    within_tolerance: bool
    markdown_dollars_cents: int
    shrink_dollars_cents: int
    override_reason: Optional[str]
    dispute_reason: Optional[str]
    posted_by_user_id: Optional[str]
    status: str
