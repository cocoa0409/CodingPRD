"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD entity descriptions. All fields use PRD-exact names.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------- Status enums ----------

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccessStatus(str, Enum):
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class PetAggressionFlag(str, Enum):
    NONE = "NONE"
    CAUTION = "CAUTION"
    AGGRESSIVE = "AGGRESSIVE"


class VisitFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    TWICE_WEEKLY = "TWICE_WEEKLY"
    DAILY = "DAILY"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AddonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class SkipReason(str, Enum):
    VACATION = "VACATION"
    WEATHER_HOLD = "WEATHER_HOLD"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    HOA_DIRECTIVE = "HOA_DIRECTIVE"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class SkipSource(str, Enum):
    VACATION = "VACATION"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    TECH_CANNOT_ACCESS = "TECH_CANNOT_ACCESS"
    PET_SAFETY = "PET_SAFETY"
    OTHER = "OTHER"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class LineType(str, Enum):
    SUBSCRIPTION_FEE_PRORATED = "SUBSCRIPTION_FEE_PRORATED"
    VISIT_CHARGE = "VISIT_CHARGE"
    ADDON_CHARGE = "ADDON_CHARGE"
    VACATION_CREDIT = "VACATION_CREDIT"
    SATISFACTION_CREDIT = "SATISFACTION_CREDIT"
    ADJUSTMENT = "ADJUSTMENT"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class IssueCategory(str, Enum):
    MISSED_SPOT = "MISSED_SPOT"
    LATE_ARRIVAL = "LATE_ARRIVAL"
    GATE_ISSUE = "GATE_ISSUE"
    PET_SAFETY = "PET_SAFETY"
    BILLING = "BILLING"
    OTHER = "OTHER"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    OPERATIONS_MANAGER = "OperationsManager"
    BILLING_ADMIN = "BillingAdmin"


# ---------- Entity TypedDicts ----------

# common_fields: true -> id + created_at + updated_at + version
class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    account_status: str
    credit_balance_cents: int
    lifetime_visits_completed: int
    satisfaction_rolling_avg: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Yard(TypedDict, total=False):
    id: str
    customer_id: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    yard_size_sqft: int
    pet_count: int
    is_multifamily_common_area: bool
    hoa_account_code: Optional[str]
    service_region_code: str
    created_at: str
    updated_at: str
    version: int


class PropertyAccessProfile(TypedDict, total=False):
    id: str
    yard_id: str
    gate_access_code: str
    gate_instructions: str
    pet_on_premises: bool
    pet_aggression_flag: str
    access_status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    plan_code: str
    display_name: str
    visit_frequency: str
    applies_to_multifamily: bool
    base_monthly_fee_cents: int
    yard_tier_thresholds: List[int]
    yard_tier_surcharges_cents: List[int]
    pet_tier_thresholds: List[int]
    pet_tier_surcharges_cents: List[int]
    multifamily_multiplier_bp: int
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAddon(TypedDict, total=False):
    id: str
    addon_code: str
    display_name: str
    price_cents_per_visit: int
    addon_status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    yard_id: str
    plan_id: str
    status: str
    started_on: Optional[str]
    next_billing_anchor_date: Optional[str]
    monthly_fee_cents_snapshot: Optional[int]
    pending_plan_change_id: Optional[str]
    plan_change_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceRoute(TypedDict, total=False):
    id: str
    route_code: str
    service_date: str
    service_region_code: str
    assigned_technician_id: Optional[str]
    max_visit_capacity: int
    committed_visit_count: int
    route_load_factor_bp: int
    route_status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    employee_code: str
    certified_for_aggressive_pets: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class VacationWindow(TypedDict, total=False):
    id: str
    subscription_id: str
    start_date: str
    end_date: str
    skip_reason: str
    window_status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    subscription_id: str
    service_route_id: Optional[str]
    scheduled_date: str
    scheduled_window_start: str
    scheduled_window_end: str
    status: str
    skip_source: Optional[str]
    addon_ids: List[str]
    tech_safety_ack_at: Optional[str]
    provisional_visit_charge_cents: Optional[int]
    final_visit_charge_cents: Optional[int]
    completed_at: Optional[str]
    invoiced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    billing_period_start: str
    billing_period_end: str
    invoice_status: str
    subtotal_cents: int
    credits_applied_cents: int
    total_due_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at; NO updated_at, NO version.
class InvoiceLineItem(TypedDict, total=False):
    id: str
    invoice_id: str
    visit_id: Optional[str]
    line_type: str
    description: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    applied_addon_id: Optional[str]
    created_at: str


class SatisfactionReport(TypedDict, total=False):
    id: str
    customer_id: str
    visit_id: str
    rating: int
    issue_category: str
    report_status: str
    resolution_credit_cents: Optional[int]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
