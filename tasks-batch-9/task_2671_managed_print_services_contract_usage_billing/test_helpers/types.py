"""Domain types for the managed print services API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    BILLING_ANALYST = "BillingAnalyst"
    FLEET_OPS_CONTROLLER = "FleetOpsController"
    FIELD_TECHNICIAN = "FieldTechnician"
    CUSTOMER_ADMIN = "CustomerAdmin"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATING = "TERMINATING"
    CLOSED = "CLOSED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    NONPAYMENT = "NONPAYMENT"
    DISPUTE = "DISPUTE"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class ServiceScope(str, Enum):
    BASIC = "BASIC"
    FULL = "FULL"


class PageClass(str, Enum):
    MONO = "MONO"
    COLOR = "COLOR"


class SecureReleaseState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    PENDING_VALIDATION = "PENDING_VALIDATION"
    CONFIGURED = "CONFIGURED"
    FAILED = "FAILED"


class ReleaseMethod(str, Enum):
    NONE = "NONE"
    BADGE = "BADGE"
    PIN = "PIN"


class ProbeResult(str, Enum):
    PASS = "PASS"
    DEFERRED = "DEFERRED"
    FAIL = "FAIL"


class DeviceLifecycleState(str, Enum):
    ASSESSED = "ASSESSED"
    PLACED = "PLACED"
    NETWORKED = "NETWORKED"
    ACTIVE = "ACTIVE"
    SERVICE_HOLD = "SERVICE_HOLD"
    RETRIEVED = "RETRIEVED"
    REMOVED = "REMOVED"


class DeviceSupplyState(str, Enum):
    SUPPLY_OK = "SUPPLY_OK"
    SUPPLY_LOW = "SUPPLY_LOW"
    SUPPLY_ORDERED = "SUPPLY_ORDERED"
    SUPPLY_BLOCKED = "SUPPLY_BLOCKED"


class RightSizingAction(str, Enum):
    NONE = "NONE"
    RETAIN = "RETAIN"
    DOWNGRADE = "DOWNGRADE"
    UPGRADE = "UPGRADE"
    CONSOLIDATE = "CONSOLIDATE"


class SkillLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class MeterReadSource(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"
    SWEEP_ESTIMATE = "SWEEP_ESTIMATE"


class MeterReadStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    ACCEPTED = "ACCEPTED"
    EXCEPTION = "EXCEPTION"
    VOID = "VOID"


class ExceptionReason(str, Enum):
    NONE = "NONE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    ROLLBACK = "ROLLBACK"
    IMPLAUSIBLE_SPIKE = "IMPLAUSIBLE_SPIKE"


class VoidedReason(str, Enum):
    NONE = "NONE"
    WRONG_DEVICE = "WRONG_DEVICE"
    DUPLICATE_CAPTURE = "DUPLICATE_CAPTURE"
    CUSTOMER_DISPUTE = "CUSTOMER_DISPUTE"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    SWEPT = "SWEPT"
    PROVISIONAL = "PROVISIONAL"
    CLOSED = "CLOSED"


class StatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ProjectionBasis(str, Enum):
    PROJECTED = "PROJECTED"
    ACTUAL = "ACTUAL"


class PartType(str, Enum):
    TONER_BLACK = "TONER_BLACK"
    TONER_COLOR = "TONER_COLOR"


class OrderStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderTriggerSource(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    MANUAL = "MANUAL"


class CancelReason(str, Enum):
    NONE = "NONE"
    HOARDING_CONTROL = "HOARDING_CONTROL"
    WRONG_PART = "WRONG_PART"
    DEVICE_REMOVED = "DEVICE_REMOVED"
    READ_VOIDED = "READ_VOIDED"


class TicketSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    PARTS_HOLD = "PARTS_HOLD"
    ONSITE = "ONSITE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class RemovalOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    SANITIZED = "SANITIZED"
    SETTLED = "SETTLED"


class SanitizationMethod(str, Enum):
    NONE = "NONE"
    CRYPTO_ERASE = "CRYPTO_ERASE"
    OVERWRITE_3PASS = "OVERWRITE_3PASS"
    PHYSICAL_DESTRUCTION = "PHYSICAL_DESTRUCTION"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class ServiceContract(TypedDict):
    id: str
    customer_name: str
    term_months: int
    status: str
    included_service_scope: str
    minimum_mono_pages_per_period: int
    minimum_color_pages_per_period: int
    monthly_service_fee_cents: int
    response_sla_hours_critical: int
    response_sla_hours_standard: int
    labor_rate_cents_per_hour: int
    early_termination_fee_cents: int
    active_device_count: int
    consumables_committed_cents: int
    true_up_balance_cents: int
    lifetime_billed_cents: int
    suspension_count: int
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


# Rate-card rows are immutable: they carry only id and created_at.
class CostTier(TypedDict):
    id: str
    contract_id: str
    page_class: str
    tier_index: int
    from_page: int
    to_page: Optional[int]
    rate_micro_dollars_per_page: int
    created_at: str


class Site(TypedDict):
    id: str
    contract_id: str
    name: str
    address_region: str
    secure_release_state: str
    release_method: str
    network_vlan_tag: Optional[int]
    toner_unit_cap: int
    open_toner_units: int
    created_at: str
    updated_at: str
    version: int


class SparePartStock(TypedDict):
    id: str
    site_id: str
    part_sku: str
    on_hand_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    contract_id: str
    site_id: str
    asset_tag: str
    model_code: str
    color_capable: bool
    rated_monthly_duty_cycle: int
    lifecycle_state: str
    supply_state: str
    toner_level_pct: int
    last_accepted_mono_meter: int
    last_accepted_color_meter: int
    last_read_at: Optional[str]
    lifetime_mono_pages: int
    lifetime_color_pages: int
    pages_since_last_cartridge: int
    offline_exception_count: int
    waste_event_count: int
    secure_release_enrolled: bool
    assessed_monthly_mono_pages: int
    assessed_monthly_color_pages: int
    baseline_cost_micro_dollars_per_page: int
    baseline_overhead_cents_per_month: int
    right_sizing_action: str
    refresh_due: bool
    replaced_by_device_id: Optional[str]
    removal_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    home_region: str
    skill_level: str
    travel_buffer_minutes: int
    open_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class MeterRead(TypedDict):
    id: str
    device_id: str
    billing_period_id: str
    source: str
    status: str
    mono_meter: int
    color_meter: int
    toner_level_pct: int
    coverage_start: str
    coverage_end: str
    mono_delta: int
    color_delta: int
    exception_reason: str
    read_at: str
    submitted_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    voided_reason: str
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    status: str
    sweep_run_count: int
    exception_open_count: int
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict):
    id: str
    billing_period_id: str
    variant: str
    projection_basis: str
    mono_pages_billed: int
    color_pages_billed: int
    mono_tier_index: int
    color_tier_index: int
    mono_rate_micro_dollars_per_page: int
    color_rate_micro_dollars_per_page: int
    usage_subtotal_cents: int
    shortfall_pages: int
    shortfall_cents: int
    service_labor_cents: int
    sla_credit_cents: int
    waste_penalty_cents: int
    total_cents: int
    generated_at: str
    created_at: str
    updated_at: str
    version: int


# Statement lines are append-only: they carry only id and created_at.
class StatementLine(TypedDict):
    id: str
    statement_id: str
    device_id: str
    page_class: str
    pages: int
    rate_micro_dollars_per_page: int
    amount_cents: int
    created_at: str


class ConsumableOrder(TypedDict):
    id: str
    device_id: str
    part_type: str
    quantity: int
    unit_price_cents: int
    committed_cents: int
    status: str
    trigger_source: str
    pages_since_last_cartridge_at_order: int
    waste_flagged: bool
    delivered_at: Optional[str]
    cancel_reason: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    device_id: str
    assigned_technician_id: Optional[str]
    severity: str
    status: str
    symptom_code: str
    part_sku: Optional[str]
    opened_at: str
    respond_by: str
    window_start: Optional[str]
    window_end: Optional[str]
    hold_started_at: Optional[str]
    parts_hold_hours: int
    responded_at: Optional[str]
    hours_late: int
    labor_hours: float
    labor_cents: int
    sla_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class QuarterlyReview(TypedDict):
    id: str
    contract_id: str
    quarter_label: str
    status: str
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    baseline_savings_cents: int
    realized_savings_cents: int
    volume_trend_pct: float
    retain_count: int
    downgrade_count: int
    upgrade_count: int
    consolidate_count: int
    refresh_due_device_count: int
    created_at: str
    updated_at: str
    version: int


class RemovalOrder(TypedDict):
    id: str
    contract_id: str
    status: str
    scheduled_for: str
    device_count: int
    sanitization_method: str
    sanitization_certificate_ref: Optional[str]
    unbilled_pages_charge_cents: int
    early_termination_fee_applied_cents: int
    device_residual_credit_cents: int
    gross_settlement_cents: int
    sanitization_fee_cents: int
    net_settlement_cents: int
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
