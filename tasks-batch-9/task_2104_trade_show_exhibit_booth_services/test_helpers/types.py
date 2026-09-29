"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EXHIBITOR = "Exhibitor"
    SHOW_OPERATIONS = "ShowOperations"
    WAREHOUSE_AGENT = "WarehouseAgent"
    LABOR_SUPERVISOR = "LaborSupervisor"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FINANCE_CONTROLLER = "FinanceController"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Trade(str, Enum):
    RIGGING = "RIGGING"
    ELECTRICAL = "ELECTRICAL"
    CARPENTRY = "CARPENTRY"
    MATERIAL_HANDLING = "MATERIAL_HANDLING"
    CLEANING = "CLEANING"


class WarehouseStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    CLOSED = "CLOSED"


class ShowStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_ORDERS = "OPEN_FOR_ORDERS"
    ADVANCE_CLOSED = "ADVANCE_CLOSED"
    MOVE_IN = "MOVE_IN"
    ON_SITE = "ON_SITE"
    MOVE_OUT = "MOVE_OUT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExhibitorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BoothType(str, Enum):
    INLINE = "INLINE"
    CORNER = "CORNER"
    PENINSULA = "PENINSULA"
    ISLAND = "ISLAND"


class BoothPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PostureReason(str, Enum):
    EXHIBITOR_SUSPENDED = "EXHIBITOR_SUSPENDED"
    CREDIT_LIMIT_BREACHED = "CREDIT_LIMIT_BREACHED"
    SHOW_CLOSED = "SHOW_CLOSED"
    SHOW_CANCELLED = "SHOW_CANCELLED"
    LABOR_NO_SHOW = "LABOR_NO_SHOW"
    FREIGHT_HOLD = "FREIGHT_HOLD"
    CHANGE_ORDER_APPROVED = "CHANGE_ORDER_APPROVED"


class AcquisitionMode(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class AssetStatus(str, Enum):
    IN_DESIGN = "IN_DESIGN"
    FABRICATED = "FABRICATED"
    IN_STORAGE = "IN_STORAGE"
    STAGED = "STAGED"
    ON_SHOW_FLOOR = "ON_SHOW_FLOOR"
    IN_REFURB = "IN_REFURB"
    RETIRED = "RETIRED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    RELEASED_TO_FAB = "RELEASED_TO_FAB"
    CANCELLED = "CANCELLED"


class DesignDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    CANCEL = "CANCEL"


class ServiceType(str, Enum):
    ELECTRICAL = "ELECTRICAL"
    RIGGING = "RIGGING"
    MATERIAL_HANDLING = "MATERIAL_HANDLING"
    CLEANING = "CLEANING"
    INSTALL_DISMANTLE = "INSTALL_DISMANTLE"


class DeadlineTier(str, Enum):
    ADVANCE = "ADVANCE"
    STANDARD = "STANDARD"
    ONSITE = "ONSITE"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    REBILL_PENDING = "REBILL_PENDING"
    SETTLED = "SETTLED"
    CREDITED = "CREDITED"


class CrateType(str, Enum):
    WOOD_CRATE = "WOOD_CRATE"
    FIBER_CASE = "FIBER_CASE"
    LOOSE_UNCRATED = "LOOSE_UNCRATED"


class CrateStatus(str, Enum):
    REGISTERED = "REGISTERED"
    AT_ADVANCE_WAREHOUSE = "AT_ADVANCE_WAREHOUSE"
    IN_TRANSIT_TO_SHOW = "IN_TRANSIT_TO_SHOW"
    ON_SHOW_FLOOR = "ON_SHOW_FLOOR"
    EMPTY_STORED = "EMPTY_STORED"
    OUTBOUND_STAGED = "OUTBOUND_STAGED"
    RETURNED_TO_WAREHOUSE = "RETURNED_TO_WAREHOUSE"
    RELEASED_TO_CARRIER = "RELEASED_TO_CARRIER"
    LOST = "LOST"


class DrayageChannel(str, Enum):
    ADVANCE_WAREHOUSE = "ADVANCE_WAREHOUSE"
    DIRECT_TO_SHOW = "DIRECT_TO_SHOW"


class ShipmentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED_TO_BOOTH = "DELIVERED_TO_BOOTH"
    CLOSED = "CLOSED"


class LaborCallStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LaborOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class ChangeTargetType(str, Enum):
    SERVICE_ORDER = "SERVICE_ORDER"
    LABOR_CALL = "LABOR_CALL"
    EXHIBIT_DESIGN = "EXHIBIT_DESIGN"


class DeltaKind(str, Enum):
    QTY_INCREASE = "QTY_INCREASE"
    QTY_DECREASE = "QTY_DECREASE"
    CREW_INCREASE = "CREW_INCREASE"
    SCOPE_UPGRADE = "SCOPE_UPGRADE"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class ChangeOrderDecision(str, Enum):
    START_REVIEW = "START_REVIEW"
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    REJECT = "REJECT"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class CoverageBasis(str, Enum):
    TARIFF_LIABILITY = "TARIFF_LIABILITY"
    DECLARED_VALUE = "DECLARED_VALUE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class RefurbScope(str, Enum):
    GRAPHICS_REFRESH = "GRAPHICS_REFRESH"
    STRUCTURAL_REPAIR = "STRUCTURAL_REPAIR"
    FULL_REBUILD = "FULL_REBUILD"


class RefurbStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LicenseStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity shapes. Every resource except the service order line carries the full
# audit triple (created_at, updated_at, version); the line carries only id and
# created_at.
# ---------------------------------------------------------------------------

class Venue(TypedDict):
    id: str
    name: str
    city: str
    straight_time_start_hhmm: str
    straight_time_end_hhmm: str
    max_forklift_capacity_lbs: int
    hanging_sign_booth_types: List[str]
    dock_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnionJurisdiction(TypedDict):
    id: str
    venue_id: str
    trade: str
    straight_time_rate_cents_per_hour: int
    overtime_multiplier: float
    doubletime_multiplier: float
    min_call_hours: float
    crew_max_size: int
    exhibitor_self_install_allowed: bool
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    name: str
    city: str
    storage_rate_cents_per_cwt_per_month: int
    free_days: int
    capacity_cwt: int
    dock_capacity_cwt: int
    committed_cwt: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict):
    id: str
    venue_id: str
    name: str
    discount_deadline: str
    advance_warehouse_deadline: str
    move_in_start: str
    move_in_end: str
    show_open: str
    show_close: str
    move_out_end: str
    status: str
    committed_labor_hours: float
    cancelled_labor_call_count: int
    created_at: str
    updated_at: str
    version: int


class Exhibitor(TypedDict):
    id: str
    company_name: str
    contact_email: str
    credit_limit_cents: int
    account_balance_cents: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    show_id: str
    exhibitor_id: str
    booth_number: str
    sqft: int
    booth_type: str
    posture: str
    posture_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExhibitAsset(TypedDict):
    id: str
    exhibitor_id: str
    current_warehouse_id: Optional[str]
    derived_from_asset_id: Optional[str]
    acquisition_mode: str
    list_value_cents: int
    shipping_weight_lbs: int
    condition_grade: str
    refurb_cycles_count: int
    stored_since: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExhibitDesign(TypedDict):
    id: str
    exhibitor_id: str
    booth_id: str
    asset_id: Optional[str]
    sqft: int
    linear_feet: int
    has_hanging_sign: bool
    expected_show_count: int
    selected_acquisition_mode: str
    rental_quote_cents: Optional[int]
    purchase_quote_cents: Optional[int]
    rental_per_show_cents: Optional[int]
    purchase_per_show_cents: Optional[int]
    breakeven_show_count: Optional[int]
    quoted_price_cents: Optional[int]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    booth_id: str
    invoice_id: Optional[str]
    service_type: str
    window_start: Optional[str]
    window_end: Optional[str]
    ordered_at: str
    deadline_tier: str
    tier_multiplier: float
    subtotal_cents: int
    volume_discount_cents: int
    discounted_base_cents: int
    service_fee_cents: int
    total_cents: int
    fulfillment_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrderLine(TypedDict):
    """Immutable priced line: id and created_at only, no updated_at, no version."""
    id: str
    service_order_id: str
    line_seq: int
    catalog_item_code: str
    unit_qty: int
    unit_rate_cents: int
    discount_pct: float
    line_total_cents: int
    created_at: str


class Crate(TypedDict):
    id: str
    exhibitor_id: str
    asset_id: Optional[str]
    warehouse_id: Optional[str]
    shipment_id: Optional[str]
    crate_label: str
    crate_type: str
    weight_lbs: int
    stored_since: Optional[str]
    storage_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrayageShipment(TypedDict):
    id: str
    show_id: str
    exhibitor_id: str
    warehouse_id: Optional[str]
    channel: str
    crate_ids: List[str]
    received_at: str
    dock_window_start: str
    dock_window_end: str
    declared_value_coverage: bool
    gross_weight_lbs: int
    billable_cwt: int
    drayage_charge_cents: int
    hold_flag: bool
    hold_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborCall(TypedDict):
    id: str
    booth_id: str
    jurisdiction_id: str
    service_order_id: Optional[str]
    trade: str
    scheduled_start: str
    scheduled_end: str
    crew_size: int
    self_install_requested: bool
    actual_start: Optional[str]
    actual_end: Optional[str]
    scheduled_hours: float
    billed_hours: Optional[float]
    st_hours: Optional[float]
    ot_hours: Optional[float]
    dt_hours: Optional[float]
    labor_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    booth_id: str
    target_type: str
    target_id: str
    delta_kind: str
    delta_qty: Optional[int]
    reason: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    price_delta_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    exhibitor_id: str
    show_id: str
    service_order_ids: List[str]
    subtotal_cents: int
    adjustments_cents: int
    total_cents: int
    settled_cents: int
    issued_by_user_id: Optional[str]
    voided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    exhibitor_id: str
    asset_id: str
    crate_id: Optional[str]
    shipment_id: Optional[str]
    claim_type: str
    declared_value_cents: int
    incident_at: str
    coverage_basis: str
    settlement_cents: Optional[int]
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefurbWorkOrder(TypedDict):
    id: str
    asset_id: str
    warehouse_id: str
    scope: str
    estimate_cents: int
    actual_cents: Optional[int]
    variance_cents: Optional[int]
    condition_grade_after: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeadCaptureLicense(TypedDict):
    id: str
    booth_id: str
    device_count: int
    included_leads: int
    ingested_badge_ids: List[str]
    leads_ingested_count: int
    billable_overage_leads: int
    lead_overage_cents: int
    license_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
