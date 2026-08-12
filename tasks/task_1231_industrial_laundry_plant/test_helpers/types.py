"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    ROUTE_DRIVER = "RouteDriver"
    PLANT_OPERATOR = "PlantOperator"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER_CONTACT = "CustomerContact"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerKind(str, Enum):
    HEALTHCARE = "HEALTHCARE"
    HOSPITALITY = "HOSPITALITY"


class BillingMode(str, Enum):
    RENTAL = "RENTAL"
    COG = "COG"


class WashFormula(str, Enum):
    WF_STANDARD = "WF_STANDARD"
    WF_THERMAL_DISINFECT = "WF_THERMAL_DISINFECT"
    WF_CHEM_DISINFECT = "WF_CHEM_DISINFECT"
    WF_HEAVY_SOIL = "WF_HEAVY_SOIL"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    DISPUTED = "DISPUTED"


class SoiledCartStatus(str, Enum):
    DECLARED = "DECLARED"
    RECEIVED = "RECEIVED"
    SORTED = "SORTED"
    VOIDED = "VOIDED"


class SortBatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SortDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    STAIN = "STAIN"
    TEAR = "TEAR"
    CONTAMINATION = "CONTAMINATION"


class WashLoadStatus(str, Enum):
    STAGED = "STAGED"
    RUNNING = "RUNNING"
    AWAITING_TEST = "AWAITING_TEST"
    TESTED_PASS = "TESTED_PASS"
    TESTED_FAIL = "TESTED_FAIL"
    REWASH_PENDING = "REWASH_PENDING"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class HygienicTestResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class FinishRunStatus(str, Enum):
    QUEUED = "QUEUED"
    TALLIED = "TALLIED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class GarmentState(str, Enum):
    AT_CUSTOMER = "AT_CUSTOMER"
    IN_TRANSIT_SOILED = "IN_TRANSIT_SOILED"
    SOILED_RECEIVED = "SOILED_RECEIVED"
    WASHING = "WASHING"
    CLEAN_STOCK = "CLEAN_STOCK"
    LOADED_OUT = "LOADED_OUT"
    LOST = "LOST"


class DeliveryStatus(str, Enum):
    MANIFESTED = "MANIFESTED"
    DELIVERED = "DELIVERED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class DiscrepancyStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts -------------------------------------------------------
# All resources except UtilityReading carry id + created_at + updated_at +
# version (PRD §2.4). UtilityReading is immutable and carries only id +
# created_at.


class Plant(TypedDict, total=False):
    id: str
    name: str
    reject_rate_alert_pct: float
    par_shortage_alert_pieces: int
    utility_baseline_kwh_per_lb: float
    utility_baseline_gal_per_lb: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    plant_id: str
    name: str
    customer_kind: str
    billing_mode: str
    chip_tracking_enabled: bool
    credit_limit_cents: int
    account_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LinenCategory(TypedDict, total=False):
    id: str
    plant_id: str
    code: str
    piece_weight_lb: float
    wash_formula_code: str
    hygienic_test_required: bool
    replacement_cost_cents: int
    cog_wash_rate_cents_per_lb: int
    created_at: str
    updated_at: str
    version: int


class CustomerParLevel(TypedDict, total=False):
    id: str
    customer_id: str
    category_id: str
    par_pieces: int
    current_on_site_pieces: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    plant_id: str
    service_date: str
    driver_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    customer_id: str
    sequence_index: int
    declared_soiled_weight_lb: float
    actual_soiled_weight_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SoiledCart(TypedDict, total=False):
    id: str
    stop_id: str
    cart_tag: str
    scale_weight_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SortBatch(TypedDict, total=False):
    id: str
    plant_id: str
    stop_id: str
    total_sorted_pieces: int
    accepted_pieces: int
    rejected_pieces: int
    reject_rate_pct: float
    alert_raised: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SortItem(TypedDict, total=False):
    id: str
    batch_id: str
    category_id: str
    pieces: int
    disposition: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WashLoad(TypedDict, total=False):
    id: str
    plant_id: str
    batch_id: str
    category_id: str
    machine_id: str
    scheduled_start: str
    scheduled_end: str
    formula_code: str
    rewash_count: int
    hygienic_test_result: str
    clean_weight_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishRun(TypedDict, total=False):
    id: str
    plant_id: str
    wash_load_id: str
    line_id: str
    scheduled_start: str
    scheduled_end: str
    pieces_in: int
    pieces_out: int
    linen_loss_pieces: int
    throughput_pieces_per_hour: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Garment(TypedDict, total=False):
    id: str
    customer_id: str
    category_id: str
    chip_code: str
    state: str
    lost_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    stop_id: str
    category_id: str
    pieces_promised: int
    pieces_delivered: int
    shortfall_pieces: int
    overage_pieces: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict, total=False):
    id: str
    delivery_id: str
    claimed_shortfall_pieces: int
    approved_shortfall_pieces: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    billing_period_start: str
    billing_period_end: str
    linen_charges_cents: int
    lost_item_charges_cents: int
    utility_surcharge_cents: int
    credits_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityReading(TypedDict, total=False):
    """Immutable monthly posting: carries ONLY id + created_at (PRD §2.4).

    updated_at and version are deliberately absent.
    """
    id: str
    plant_id: str
    period_month: str
    kwh_used: float
    gallons_used: float
    clean_lbs_processed: float
    kwh_rate_cents: int
    gallon_rate_cents: int
    created_at: str
