"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    ACCOUNT_OWNER = "AccountOwner"
    BILLING_CLERK = "BillingClerk"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ServiceRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    CREDITED = "CREDITED"


class ItemServiceStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    ASSESSED = "ASSESSED"
    IN_WORK = "IN_WORK"
    DONE = "DONE"
    DELIVERED = "DELIVERED"
    REWORK_QUEUED = "REWORK_QUEUED"
    RETURNED_UNSERVICED = "RETURNED_UNSERVICED"
    ABANDONED = "ABANDONED"


class CustodyLocation(str, Enum):
    CUSTOMER = "CUSTOMER"
    VAN = "VAN"
    BENCH = "BENCH"
    LOCKER = "LOCKER"
    DELIVERED = "DELIVERED"
    ABANDONED = "ABANDONED"


class AuthorizationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"


class RouteRunStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    SERVICED = "SERVICED"
    SKIPPED = "SKIPPED"
    SPILLED = "SPILLED"
    CANCELLED = "CANCELLED"


class CompartmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OCCUPIED = "OCCUPIED"
    HOLD_EXPIRED = "HOLD_EXPIRED"


class LoanerUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    INSPECTION = "INSPECTION"
    RETIRED = "RETIRED"


class LoanerIssueStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class ItemClass(str, Enum):
    CHEF_KNIFE = "CHEF_KNIFE"
    SERRATED_BREAD = "SERRATED_BREAD"
    SALON_SHEAR = "SALON_SHEAR"
    CLIPPER_BLADE = "CLIPPER_BLADE"
    DELI_SLICER_BLADE = "DELI_SLICER_BLADE"
    GARDEN_PRUNER = "GARDEN_PRUNER"
    MANDOLINE_BLADE = "MANDOLINE_BLADE"


class DamageTier(str, Enum):
    ROUTINE_HONE = "ROUTINE_HONE"
    CHIP_REPAIR = "CHIP_REPAIR"
    RE_TIP = "RE_TIP"
    HANDLE_WORK = "HANDLE_WORK"


class Channel(str, Enum):
    VAN_ROUTE = "VAN_ROUTE"
    LOCKER = "LOCKER"
    REWORK = "REWORK"


class LineSource(str, Enum):
    SERVICE = "SERVICE"
    PART = "PART"
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    LATE_FEE = "LATE_FEE"
    WARRANTY_CREDIT = "WARRANTY_CREDIT"
    PRORATION_CREDIT = "PRORATION_CREDIT"


class AllowanceKind(str, Enum):
    GRANTED = "GRANTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    RESTORED = "RESTORED"


# --- Entities carrying id + created_at + updated_at + version -------------

class Account(TypedDict):
    id: str
    name: str
    account_type: str
    zone_code: str
    billing_mode: str
    tax_exempt: bool
    credit_limit_cents: int
    contact_email: str
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PlanTier(TypedDict):
    id: str
    code: str
    monthly_fee_cents: int
    included_items_per_cycle: int
    overage_discount_pct: float
    allowed_cadences: List[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    plan_tier_id: str
    cadence: str
    anchor_date: str
    status: str
    effective_monthly_fee_cents: int
    included_items_this_cycle: int
    allowance_remaining: int
    cycle_index: int
    cycle_start_date: str
    cycle_end_date: str
    next_service_date: Optional[str]
    skip_count_this_cycle: int
    paused_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ItemClassSpec(TypedDict):
    id: str
    item_class: str
    bevel_angle_degrees: int
    base_service_minutes: int
    list_price_cents: int
    required_certification: str
    price_tier: str
    min_locker_size: str
    loaner_eligible: bool
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    account_id: str
    subscription_id: Optional[str]
    origin_warranty_claim_id: Optional[str]
    channel: str
    priority: str
    requested_date: str
    locker_site_code: Optional[str]
    locker_high_value_authorized: bool
    status: str
    billing_status: str
    item_count: int
    quoted_total_cents: int
    final_total_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RequestItem(TypedDict):
    id: str
    service_request_id: str
    item_class_spec_id: str
    bench_day_id: Optional[str]
    rework_of_request_item_id: Optional[str]
    assessed_by_technician_id: Optional[str]
    item_class: str
    declared_damage_tier: str
    assessed_damage_tier: Optional[str]
    quoted_gross_cents: int
    final_gross_cents: int
    charged_service_cents: int
    part_fee_cents: int
    service_minutes_declared: int
    service_minutes_assessed: Optional[int]
    requires_reauthorization: bool
    authorization_status: str
    service_status: str
    custody_location: str
    allowance_applied: bool
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    certifications: List[str]
    created_at: str
    updated_at: str
    version: int


class Van(TypedDict):
    id: str
    code: str
    default_service_minute_budget: int
    default_stop_cap: int
    created_at: str
    updated_at: str
    version: int


class RouteRun(TypedDict):
    id: str
    van_id: str
    technician_id: str
    run_date: str
    zone_code: str
    service_minute_budget: int
    stop_cap: int
    day_window_start: str
    day_window_end: str
    status: str
    scheduled_stop_count: int
    booked_service_minutes: int
    committed_minutes_provisional: int
    committed_minutes_final: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_run_id: str
    service_request_id: str
    account_id: str
    spilled_from_route_run_id: Optional[str]
    sequence: int
    arrival_window_start: str
    arrival_window_end: str
    stop_service_minutes: int
    spill_hop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LockerCompartment(TypedDict):
    id: str
    site_code: str
    size: str
    current_service_request_id: Optional[str]
    status: str
    access_code: Optional[str]
    hold_expires_at: Optional[str]
    last_released_at: Optional[str]
    stored_item_count: int
    stored_value_cents: int
    created_at: str
    updated_at: str
    version: int


class BenchDay(TypedDict):
    id: str
    bench_date: str
    bench_minute_budget: int
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class LoanerUnit(TypedDict):
    id: str
    item_class_spec_id: str
    grade: str
    cycle_ceiling: int
    cycle_count: int
    damage_reported: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerIssue(TypedDict):
    id: str
    loaner_unit_id: str
    service_request_id: str
    requested_grade: str
    issued_at: str
    due_at: str
    returned_at: Optional[str]
    delay_attribution: Optional[str]
    late_fee_cents: int
    substituted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    request_item_id: str
    account_id: str
    rework_service_request_id: Optional[str]
    decided_by_technician_id: Optional[str]
    reason: str
    abuse_finding: bool
    resubmit_count: int
    credit_basis_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    service_request_id: Optional[str]
    billing_mode: str
    billing_period: Optional[str]
    taxable_subtotal_cents: int
    nontaxable_subtotal_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: id + created_at only ---------------------------

class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    request_item_id: Optional[str]
    source_warranty_claim_id: Optional[str]
    source: str
    description: str
    amount_cents: int
    taxable: bool
    sequence_index: int
    created_at: str


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    applied_at: str
    resulting_invoice_status: str
    created_at: str


class AllowanceLedgerEntry(TypedDict):
    id: str
    subscription_id: str
    request_item_id: Optional[str]
    cycle_index: int
    kind: str
    quantity: int
    reason: str
    created_at: str
