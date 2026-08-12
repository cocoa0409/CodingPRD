"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries `id`, `created_at`, `updated_at` and an integer
`version` (PRD 2.4).  The append-only `CreditLedgerEntry` is the single
exception: it carries `id` and `created_at` only, so its TypedDict omits
`updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    OPERATIONS_MANAGER = "OperationsManager"
    CUSTOMER_SERVICE = "CustomerService"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DevelopmentalStage(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOLER = "PRESCHOOLER"
    EARLY_SCHOOL = "EARLY_SCHOOL"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ConditionGrade(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    WORN = "WORN"


class ToyCopyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT_ON_LOAN = "OUT_ON_LOAN"
    RETURNED = "RETURNED"
    SANITIZING = "SANITIZING"
    QUARANTINED = "QUARANTINED"
    LOST = "LOST"
    SOLD = "SOLD"
    RETIRED = "RETIRED"


class WishlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    HELD = "HELD"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RotationBoxStatus(str, Enum):
    PLANNED = "PLANNED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNING = "RETURNING"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LoanStatus(str, Enum):
    PENDING_RETURN = "PENDING_RETURN"
    RETURNED = "RETURNED"
    LOST_REPORTED = "LOST_REPORTED"
    KEPT_BUYOUT = "KEPT_BUYOUT"
    SWAPPED_OUT = "SWAPPED_OUT"
    CANCELLED = "CANCELLED"


class ResolutionStatus(str, Enum):
    NONE = "NONE"
    FEE_ASSESSED = "FEE_ASSESSED"
    RESOLVED = "RESOLVED"


class DamageSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class FeeType(str, Enum):
    DAMAGE = "DAMAGE"
    MISSING_PIECES = "MISSING_PIECES"
    LOSS = "LOSS"
    LATE_RETURN = "LATE_RETURN"


class FeeStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    DISPUTED = "DISPUTED"


class ShipmentDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    LOST_IN_TRANSIT = "LOST_IN_TRANSIT"


class ShipmentEventType(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    LOST_IN_TRANSIT = "LOST_IN_TRANSIT"


class LedgerReason(str, Enum):
    PROMO_CREDIT = "PROMO_CREDIT"
    SUPPORT_ADJUSTMENT = "SUPPORT_ADJUSTMENT"
    FEE_CHARGE = "FEE_CHARGE"
    FEE_SETTLED_CARD = "FEE_SETTLED_CARD"
    FEE_SETTLED_WALLET = "FEE_SETTLED_WALLET"
    WALLET_DEBIT = "WALLET_DEBIT"
    FEE_WAIVER = "FEE_WAIVER"
    BUYOUT_CREDIT_APPLIED = "BUYOUT_CREDIT_APPLIED"


class PaymentSource(str, Enum):
    CARD = "CARD"
    WALLET_CREDIT = "WALLET_CREDIT"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class InspectionDisposition(str, Enum):
    RESTOCK = "RESTOCK"
    QUARANTINE = "QUARANTINE"


class PauseWindow(TypedDict, total=False):
    start_date: str
    end_date: str
    consumed_days: Optional[int]
    closed: bool


class ShipmentEvent(TypedDict):
    event_type: str
    occurred_at: str


# --- Entities with the full common-field set (id/created_at/updated_at/version) ---


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ChildProfile(TypedDict, total=False):
    id: str
    member_id: str
    name: str
    birthdate: str
    age_months: int
    developmental_stage: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    name: str
    monthly_fee_cents: int
    toys_per_box: int
    swap_allowance_per_cycle: int
    max_holds: int
    rotation_cadence_days: int
    rental_period_days: int
    buyout_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    member_id: str
    plan_id: str
    status: str
    next_cycle_due_at: str
    pause_windows: List[PauseWindow]
    current_pause_end: Optional[str]
    paused_days_used_365d: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict, total=False):
    id: str
    title: str
    description: str
    min_age_months: int
    max_age_months: int
    developmental_stages: List[str]
    piece_count: int
    retail_value_cents: int
    replacement_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ToyCopy(TypedDict, total=False):
    id: str
    catalog_item_id: str
    barcode: str
    condition_grade: str
    status: str
    reserved_member_id: Optional[str]
    sanitization_started_at: Optional[str]
    last_sanitized_at: Optional[str]
    sanitization_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class WishlistEntry(TypedDict, total=False):
    id: str
    member_id: str
    catalog_item_id: str
    rank: int
    status: str
    held_copy_id: Optional[str]
    hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RotationBox(TypedDict, total=False):
    id: str
    subscription_id: str
    cycle_number: int
    status: str
    swap_count: int
    delivered_at: Optional[str]
    due_date: Optional[str]
    received_at: Optional[str]
    projected_late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class BoxItem(TypedDict, total=False):
    id: str
    rotation_box_id: str
    toy_copy_id: str
    swapped_from_item_id: Optional[str]
    loan_status: str
    resolution_status: str
    condition_returned: Optional[str]
    damage_severity: Optional[str]
    missing_piece_count: int
    buyout_price_cents: Optional[int]
    wallet_applied_cents: Optional[int]
    net_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    subscription_id: str
    box_item_id: Optional[str]
    rotation_box_id: Optional[str]
    fee_type: str
    amount_cents: int
    status: str
    dispute_rounds: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    rotation_box_id: str
    direction: str
    carrier: str
    tracking_number: str
    status: str
    events: List[ShipmentEvent]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity: id + created_at only (PRD 2.4 exception) ---


class CreditLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    amount_cents: int
    reason: str
    note: str
    created_at: str
