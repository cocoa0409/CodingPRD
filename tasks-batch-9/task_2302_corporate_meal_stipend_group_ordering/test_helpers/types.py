"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --- Roles (PRD §2.1) -------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_ADMIN = "ProgramAdmin"
    BENEFITS_CONTROLLER = "BenefitsController"
    EMPLOYEE = "Employee"
    RESTAURANT = "Restaurant"


# --- Status enums -----------------------------------------------------------
class BudgetRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TaxTreatmentFlag(str, Enum):
    NONE = "NONE"
    W2_IMPUTED = "W2_IMPUTED"


class BenefitPeriodStatus(str, Enum):
    OPEN = "OPEN"
    GRACE = "GRACE"
    CLOSED = "CLOSED"


class RestaurantStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class GroupOrderStatus(str, Enum):
    COLLECTING = "COLLECTING"
    LOCKED = "LOCKED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SPLIT_AUTHORIZED = "SPLIT_AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class CreditClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTED_EMPLOYEE_FIRST = "ROUTED_EMPLOYEE_FIRST"
    ROUTED_PROPORTIONAL = "ROUTED_PROPORTIONAL"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class ImputedIncomeRecordStatus(str, Enum):
    ACCRUING = "ACCRUING"
    LOCKED = "LOCKED"
    EXPORTED = "EXPORTED"


class ExpenseExportStatus(str, Enum):
    GENERATED = "GENERATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


# --- Policy selector enums --------------------------------------------------
class TaxableBenefitMethod(str, Enum):
    DE_MINIMIS_EXCLUSION = "DE_MINIMIS_EXCLUSION"
    FULL_INCLUSION = "FULL_INCLUSION"


class RolloverPolicy(str, Enum):
    NONE = "NONE"
    CAPPED_PCT = "CAPPED_PCT"
    FULL = "FULL"


class ForecastBasis(str, Enum):
    COMMITMENT = "COMMITMENT"
    RUN_RATE = "RUN_RATE"


class OveragePolicy(str, Enum):
    PERSONAL_CARD = "PERSONAL_CARD"
    BLOCK = "BLOCK"


class TipCoveragePolicy(str, Enum):
    EMPLOYEE_PAYS_TIP = "EMPLOYEE_PAYS_TIP"
    EMPLOYER_COVERS_TIP = "EMPLOYER_COVERS_TIP"


class ClaimType(str, Enum):
    MISSING_ITEM = "MISSING_ITEM"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    NEVER_DELIVERED = "NEVER_DELIVERED"


class RoutingBasis(str, Enum):
    EMPLOYEE_FIRST = "EMPLOYEE_FIRST"
    PROPORTIONAL = "PROPORTIONAL"


class RefundDirection(str, Enum):
    EMPLOYER_CREDIT = "EMPLOYER_CREDIT"
    EMPLOYEE_CARD_REFUND = "EMPLOYEE_CARD_REFUND"


class RefundReason(str, Enum):
    CLAIM_SETTLEMENT = "CLAIM_SETTLEMENT"
    ORDER_VOID = "ORDER_VOID"


class CloseMode(str, Enum):
    GRACE = "GRACE"
    FINAL = "FINAL"


class ExportFormat(str, Enum):
    CSV_EXPENSE_REPORT = "CSV_EXPENSE_REPORT"
    PAYROLL_IMPUTED_FEED = "PAYROLL_IMPUTED_FEED"


class ResolveDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --- Entity TypedDicts ------------------------------------------------------
# Resources listed in PRD §2.4 as carrying updated_at and version.
class MealProgram(TypedDict):
    id: str
    employer_name: str
    billing_account_ref: str
    max_delivery_radius_km: float
    eligible_cuisines: List[str]
    taxable_benefit_method: str
    rollover_policy: str
    rollover_cap_pct: float
    forecast_basis: str
    program_spent_cents: int
    program_reserved_cents: int
    mtd_employer_captured_cents: int
    created_at: str
    updated_at: str
    version: int


class EmployeeGroup(TypedDict):
    id: str
    program_id: str
    name: str
    headcount_planned: int
    active_rule_count: int
    created_at: str
    updated_at: str
    version: int


class BudgetRule(TypedDict):
    id: str
    group_id: str
    effective_from: str
    per_meal_cap_cents: int
    daily_meal_limit: int
    monthly_allocation_cents: int
    eligible_weekdays: List[int]
    eligible_window_start_minute: int
    eligible_window_end_minute: int
    overage_policy: str
    tip_coverage_policy: str
    rule_sequence: Optional[int]
    drafted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    program_id: str
    group_id: str
    full_name: str
    email: str
    personal_card_on_file: bool
    tax_treatment_flag: str
    ytd_imputed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitPeriod(TypedDict):
    id: str
    employee_id: str
    budget_rule_id: str
    predecessor_period_id: Optional[str]
    period_month: str
    allocated_cents: int
    rollover_in_cents: int
    reserved_cents: int
    spent_cents: int
    available_cents: int
    forfeited_cents: int
    rollover_out_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Restaurant(TypedDict):
    id: str
    name: str
    cuisine: str
    grid_x_km: float
    grid_y_km: float
    delivery_radius_km: float
    max_concurrent_group_deliveries: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryLocation(TypedDict):
    id: str
    program_id: str
    label: str
    grid_x_km: float
    grid_y_km: float
    dock_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class GroupOrder(TypedDict):
    id: str
    program_id: str
    organizer_employee_id: str
    restaurant_id: str
    delivery_location_id: str
    cutoff_at: str
    window_start: str
    window_end: str
    per_person_limit_cents: int
    member_order_count: int
    reopen_count: int
    allocated_delivery_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    item_name: str
    unit_price_cents: int
    quantity: int


class Order(TypedDict):
    id: str
    employee_id: str
    benefit_period_id: str
    restaurant_id: str
    delivery_location_id: str
    group_order_id: Optional[str]
    requested_delivery_at: str
    lines: List[OrderLine]
    tip_cents: int
    subtotal_cents: int
    tax_cents: int
    delivery_fee_cents: int
    service_fee_cents: int
    tip_covered_by_employer_cents: int
    covered_base_cents: int
    employer_covered_cents: int
    employee_card_cents: int
    admin_fee_cents: int
    gross_total_cents: int
    employer_refunded_cents: int
    employee_refunded_cents: int
    net_charged_cents: int
    employer_net_cents: int
    taxable_cents: int
    tax_month: str
    placed_at: Optional[str]
    delivered_at: Optional[str]
    fulfillment_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict):
    id: str
    order_id: str
    claim_type: str
    line_index: Optional[int]
    claimed_cents: int
    approved_cents: int
    routing_basis: Optional[str]
    employer_credit_cents: int
    employee_refund_cents: int
    resolved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImputedIncomeRecord(TypedDict):
    id: str
    employee_id: str
    tax_month: str
    method: str
    gross_employer_paid_cents: int
    taxable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseExport(TypedDict):
    id: str
    program_id: str
    tax_month: str
    format: str
    receipt_count: int
    employer_gross_cents: int
    employer_refund_cents: int
    net_of_refunds_cents: int
    admin_fee_total_cents: int
    imputed_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: "A refund ledger entry carries only `id` and `created_at`; it has
# no `updated_at` and no `version`". No updated_at / version here on purpose.
class RefundLedgerEntry(TypedDict):
    id: str
    created_at: str
    order_id: str
    credit_claim_id: Optional[str]
    direction: str
    amount_cents: int
    reason: str
