"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource carries the common fields (id, created_at,
updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / domain enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    INTAKE_ATTENDANT = "IntakeAttendant"
    PRICER = "Pricer"
    CASHIER = "Cashier"
    DRIVER = "Driver"
    VOLUNTEER = "Volunteer"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    FINANCE_CLERK = "FinanceClerk"


class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DonorTier(str, Enum):
    STANDARD = "STANDARD"
    FREQUENT = "FREQUENT"


class BatchSource(str, Enum):
    WALK_IN = "WALK_IN"
    DONATION_DRIVE = "DONATION_DRIVE"
    PICKUP_STOP = "PICKUP_STOP"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SORTING = "SORTING"
    SORTED = "SORTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ItemCategory(str, Enum):
    CLOTHING = "CLOTHING"
    FURNITURE = "FURNITURE"
    ELECTRONICS = "ELECTRONICS"
    HOUSEWARES = "HOUSEWARES"
    BOOKS_MEDIA = "BOOKS_MEDIA"
    TOYS = "TOYS"
    COLLECTIBLES = "COLLECTIBLES"


class ItemCondition(str, Enum):
    NEW_WITH_TAGS = "NEW_WITH_TAGS"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class ItemStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SALABLE = "SALABLE"
    PRICED = "PRICED"
    ON_FLOOR = "ON_FLOOR"
    ON_HOLD = "ON_HOLD"
    SOLD = "SOLD"
    RECYCLE = "RECYCLE"
    PULLED_TO_SALVAGE = "PULLED_TO_SALVAGE"
    BALED = "BALED"
    SALVAGE = "SALVAGE"
    DISPOSED = "DISPOSED"
    SHRUNK = "SHRUNK"


class SalvageCategory(str, Enum):
    TEXTILES = "TEXTILES"
    PAPER = "PAPER"
    EWASTE = "EWASTE"
    BULK = "BULK"


class GuidelineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BaleStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    SEALED = "SEALED"
    SHIPPED = "SHIPPED"
    SETTLED = "SETTLED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class SaleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class TillStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class EmploymentType(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    TRANSITIONAL = "TRANSITIONAL"
    STAFF = "STAFF"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CAP_REACHED = "CAP_REACHED"


class ShiftRole(str, Enum):
    SORTER = "SORTER"
    PRICER = "PRICER"
    CASHIER = "CASHIER"
    DRIVER = "DRIVER"
    FLOOR = "FLOOR"
    INTAKE = "INTAKE"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RotationColor(str, Enum):
    RED = "RED"
    BLUE = "BLUE"
    GREEN = "GREEN"
    YELLOW = "YELLOW"


class TransferStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class MissionProgram(str, Enum):
    JOB_TRAINING = "JOB_TRAINING"
    YOUTH_SERVICES = "YOUTH_SERVICES"
    HOUSING_SUPPORT = "HOUSING_SUPPORT"
    GENERAL_FUND = "GENERAL_FUND"


class ReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ShrinkReason(str, Enum):
    THEFT = "THEFT"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


# ---------------------------------------------------------------------------
# Entity records (all carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

class Donor(TypedDict, total=False):
    id: str
    full_name: str
    email: Optional[str]
    address_line: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    status: str
    lifetime_donation_count: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class DonationBatch(TypedDict, total=False):
    id: str
    donor_id: str
    source: str
    pickup_stop_id: Optional[str]
    receipt_requested: bool
    status: str
    item_count: int
    untriaged_count: int
    provisional_value_cents: int
    sold_item_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonationItem(TypedDict, total=False):
    id: str
    batch_id: str
    category: str
    condition: str
    description: Optional[str]
    weight_lbs: Optional[float]
    salvage_category: Optional[str]
    appraisal_confirmed: bool
    provisional_value_cents: int
    base_price_cents: Optional[int]
    current_price_cents: Optional[int]
    markdown_round: int
    status: str
    floor_cycle_id: Optional[str]
    tag_color: Optional[str]
    hold_expires_at: Optional[str]
    value_at_shrink_cents: Optional[int]
    shrunk_cycle_id: Optional[str]
    shrink_reason: Optional[str]
    sale_id: Optional[str]
    bale_id: Optional[str]
    priced_at: Optional[str]
    sold_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingGuideline(TypedDict, total=False):
    id: str
    category: str
    base_cents: int
    demand_multiplier: float
    version_no: int
    status: str
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvageVendor(TypedDict, total=False):
    id: str
    name: str
    rates: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class SalvageBale(TypedDict, total=False):
    id: str
    category: str
    status: str
    vendor_id: Optional[str]
    weight_lbs: float
    item_count: int
    estimated_revenue_cents: int
    actual_weight_lbs: Optional[float]
    settled_revenue_cents: Optional[int]
    settled_cycle_id: Optional[str]
    sealed_at: Optional[str]
    shipped_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesTransaction(TypedDict, total=False):
    id: str
    till_session_id: str
    payment_method: str
    item_ids: List[str]
    line_count: int
    total_cents: int
    status: str
    voided_by_user_id: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TillSession(TypedDict, total=False):
    id: str
    cashier_worker_id: str
    opening_float_cents: int
    opened_at: str
    cash_sales_cents: int
    card_sales_cents: int
    expected_cash_cents: int
    counted_cash_cents: Optional[int]
    over_short_cents: Optional[int]
    status: str
    counted_by_user_id: Optional[str]
    variance_approved_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupRoute(TypedDict, total=False):
    id: str
    route_date: str
    driver_worker_id: str
    truck_capacity_cuft: float
    status: str
    stop_count: int
    total_volume_cuft: float
    created_at: str
    updated_at: str
    version: int


class PickupStop(TypedDict, total=False):
    id: str
    route_id: str
    donor_id: str
    window_start: str
    window_end: str
    estimated_volume_cuft: float
    status: str
    completed_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    full_name: str
    employment_type: str
    email: Optional[str]
    status: str
    credited_hours: float
    program_cap_hours: float
    cap_extension_hours: float
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    role_type: str
    starts_at: str
    ends_at: str
    required_headcount: int
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    worker_id: str
    status: str
    credited_hours_applied: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WeeklyCycle(TypedDict, total=False):
    id: str
    sequence_number: int
    rotation_color: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    markdown_runs_count: int
    gross_sales_cents: Optional[int]
    salvage_revenue_cents: Optional[int]
    net_revenue_cents: Optional[int]
    shrink_value_cents: Optional[int]
    shrink_rate_bp: Optional[int]
    shrink_alert_active: bool
    created_at: str
    updated_at: str
    version: int


class MissionTransfer(TypedDict, total=False):
    id: str
    cycle_id: str
    prepared_by_user_id: str
    allocations: List[Dict[str, Any]]
    gross_pool_cents: int
    reserve_pct: float
    reserve_cents: int
    net_pool_cents: int
    allocation_amounts: List[Dict[str, Any]]
    status: str
    approved_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReceipt(TypedDict, total=False):
    id: str
    batch_id: str
    donor_id: str
    receipt_number: str
    total_value_cents: int
    itemized_required: bool
    form_8283_required: bool
    status: str
    issued_at: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
