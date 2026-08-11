"""Domain types for the Buying Club & Food Co-op Order Platform.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    DROP_COORDINATOR = "DropCoordinator"
    MEMBER = "Member"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    FINANCE_OFFICER = "FinanceOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PRO = "PRO"


class TempClass(str, Enum):
    FROZEN = "FROZEN"
    CHILLED = "CHILLED"
    DRY = "DRY"


class RemainderPolicy(str, Enum):
    SHORT_FILL = "SHORT_FILL"
    ROUND_UP = "ROUND_UP"
    DROP = "DROP"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    CONSOLIDATED = "CONSOLIDATED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExceptionState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RouteRunStatus(str, Enum):
    PLANNED = "PLANNED"
    QUALIFIED = "QUALIFIED"
    DEFERRED = "DEFERRED"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    CONSOLIDATED = "CONSOLIDATED"
    DELIVERED = "DELIVERED"


class DropRunStatus(str, Enum):
    OPEN = "OPEN"
    QUALIFIED = "QUALIFIED"
    MERGED = "MERGED"
    DEFERRED = "DEFERRED"
    ROLLED_FORWARD = "ROLLED_FORWARD"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class MemberOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    FILLED = "FILLED"
    SHORT_FILLED = "SHORT_FILLED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatusAxis(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    AUTH_FAILED = "AUTH_FAILED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class OrderLineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    SHORT_FILLED = "SHORT_FILLED"
    SUBSTITUTED = "SUBSTITUTED"
    DROPPED = "DROPPED"
    ROLLED_FORWARD = "ROLLED_FORWARD"
    CANCELLED = "CANCELLED"


class SubstitutionPref(str, Enum):
    NONE = "NONE"
    ANY_SUBSTITUTE = "ANY_SUBSTITUTE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class SubstitutionOfferStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    AUTO_APPROVED = "AUTO_APPROVED"
    AUTO_DECLINED = "AUTO_DECLINED"


class PalletStatus(str, Enum):
    BUILDING = "BUILDING"
    SEALED = "SEALED"
    DELIVERED = "DELIVERED"


class PaymentKind(str, Enum):
    AUTHORIZATION = "AUTHORIZATION"
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"


class PaymentRecordStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    BALANCED = "BALANCED"
    VARIANCE_HELD = "VARIANCE_HELD"
    POSTED = "POSTED"
    VOID = "VOID"


class AccrualStatus(str, Enum):
    ACCRUED = "ACCRUED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"


class PayoutMode(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    CASH = "CASH"


class VolunteerShiftStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CreditGrantSource(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    REFUND = "REFUND"
    COMMISSION = "COMMISSION"
    ADJUSTMENT = "ADJUSTMENT"


class CreditGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class SimulatedOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RefundDestination(str, Enum):
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"


# --------------------------------------------------------------------------
# Entity shapes.  Every resource carries `id` and `created_at`; all of them
# except the price version additionally carry `updated_at` and `version`
# (PRD §2.4).
# --------------------------------------------------------------------------
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    tier: str
    tier_rank: int
    discount_pct: float
    status: str
    home_drop_point_id: str
    dues_paid_through: Optional[str]
    dues_grace_until: Optional[str]
    lifetime_dues_paid_cents: int
    credit_balance_cents: int
    is_coordinator: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    code: str
    name: str
    reefer_slots: int
    route_minimum_cents: int
    max_pallets: int
    cold_capable: bool
    created_at: str
    updated_at: str
    version: int


class DropPoint(TypedDict):
    id: str
    route_id: str
    name: str
    coordinator_member_id: Optional[str]
    drop_minimum_cents: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    sku: str
    name: str
    temp_class: str
    case_pack_units: int
    unit_weight_grams: int
    unit_cube_cm3: int
    split_allowed: bool
    remainder_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceVersion(TypedDict):
    """Append-only: carries only `id` and `created_at` of the common set."""

    id: str
    item_id: str
    effective_from: str
    case_price_cents: int
    split_unit_base_cents: int
    created_at: str


class Cycle(TypedDict):
    id: str
    code: str
    opens_at: str
    cutoff_at: str
    status: str
    locked_at: Optional[str]
    received_at: Optional[str]
    exception_deadline_at: Optional[str]
    exception_state: str
    created_at: str
    updated_at: str
    version: int


class RouteRun(TypedDict):
    id: str
    cycle_id: str
    route_id: str
    status: str
    aggregated_subtotal_cents: int
    supplier_invoice_cents: int
    freight_cents: int
    invoice_recorded_by_user_id: Optional[str]
    cold_pallet_count: int
    dry_pallet_count: int
    reefer_slots_used: int
    reefer_surcharge_cents: int
    received_subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class DropRun(TypedDict):
    id: str
    cycle_id: str
    drop_point_id: str
    route_run_id: str
    coordinator_member_id: Optional[str]
    merged_into_drop_run_id: Optional[str]
    status: str
    subtotal_cents: int
    discounted_subtotal_cents: int
    received_subtotal_cents: int
    verified_volunteer_hours: float
    volunteer_obligation_met: bool
    freight_alloc_cents: int
    reefer_alloc_cents: int
    rollforward_count: int
    created_at: str
    updated_at: str
    version: int


class MemberOrder(TypedDict):
    id: str
    member_id: str
    drop_run_id: str
    status: str
    payment_status: str
    gross_cents: int
    split_fee_cents: int
    tier_discount_cents: int
    freight_alloc_cents: int
    reefer_alloc_cents: int
    pre_credit_total_cents: int
    credit_applied_cents: int
    actual_total_cents: int
    estimated_total_cents: int
    authorized_amount_cents: int
    captured_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    member_order_id: str
    item_id: str
    qty_units: int
    rollover_opt_in: bool
    substitution_pref: str
    rolled_from_order_line_id: Optional[str]
    status: str
    bound_case_price_cents: int
    unit_price_cents: int
    is_split_unit: bool
    split_fee_per_unit_cents: int
    confirmed_units: int
    allocated_units: int
    short_units: int
    allocation_remainder_rank: int
    line_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class CaseAggregate(TypedDict):
    id: str
    route_run_id: str
    item_id: str
    overage_order_line_id: Optional[str]
    requested_units: int
    cases_ordered: int
    covered_units: int
    remainder_units: int
    overage_units: int
    dropped_units: int
    policy_applied: str
    case_price_cents: int
    units_received: int
    created_at: str
    updated_at: str
    version: int


class ReceiptLine(TypedDict):
    id: str
    route_run_id: str
    case_aggregate_id: str
    substitute_item_id: Optional[str]
    cases_received: int
    substitute_case_price_cents: Optional[int]
    units_received: int
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionOffer(TypedDict):
    id: str
    order_line_id: str
    receipt_line_id: str
    substitute_item_id: str
    offered_units: int
    original_unit_price_cents: int
    offered_unit_price_cents: int
    within_tolerance: bool
    respond_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pallet(TypedDict):
    id: str
    route_run_id: str
    temp_class: str
    sequence_index: int
    weight_grams: int
    cube_cm3: int
    unit_count: int
    requires_reefer: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    member_order_id: str
    kind: str
    method: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DropReconciliation(TypedDict):
    id: str
    drop_run_id: str
    member_charges_cents: int
    supplier_cost_cents: int
    freight_alloc_cents: int
    reefer_alloc_cents: int
    commission_cents: int
    club_margin_cents: int
    variance_cents: int
    prepared_by_user_id: str
    posted_by_user_id: Optional[str]
    posted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionAccrual(TypedDict):
    id: str
    drop_run_id: str
    coordinator_member_id: str
    base_subtotal_cents: int
    rate_applied: float
    volunteer_multiplier_applied: float
    accrued_cents: int
    clawback_cents: int
    net_cents: int
    payout_mode: Optional[str]
    payout_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    drop_run_id: str
    member_id: str
    credit_grant_id: Optional[str]
    hours: float
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditGrant(TypedDict):
    id: str
    member_id: str
    source_member_order_id: Optional[str]
    source: str
    amount_cents: int
    remaining_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
