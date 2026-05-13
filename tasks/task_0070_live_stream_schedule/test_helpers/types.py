"""Live Stream Schedule — domain types: entity TypedDicts, status enums, role enum.

Field names and enum values are taken verbatim from the PRD; tests assert against
the exact strings the implementer is supposed to emit.
"""

from enum import Enum
from typing import Optional, TypedDict, List, Any


# ---------------------------------------------------------------------------
# User roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STREAMER = "Streamer"
    OPERATIONS_REVIEWER = "OperationsReviewer"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class StreamerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLACKLISTED = "BLACKLISTED"


class StreamerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class StudioStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    CLOSED = "CLOSED"


class StudioType(str, Enum):
    SELF_OPERATED = "SELF_OPERATED"
    PARTNER = "PARTNER"


class SlotTier(str, Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class TimeSlotKind(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ProductCategory(str, Enum):
    FOOD = "FOOD"
    COSMETICS = "COSMETICS"
    ELECTRONICS = "ELECTRONICS"
    FASHION = "FASHION"
    KIDS = "KIDS"
    FINANCIAL = "FINANCIAL"


class ProductStatus(str, Enum):
    ON_SHELF = "ON_SHELF"
    OFF_SHELF = "OFF_SHELF"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    OPS_PENDING = "OPS_PENDING"
    COMPLIANCE_PENDING = "COMPLIANCE_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class OperationalStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PackageCode(str, Enum):
    STANDARD = "STANDARD"
    COMBO_HALF_DAY = "COMBO_HALF_DAY"
    COMBO_FULL_DAY = "COMBO_FULL_DAY"
    PEAK_BUNDLE = "PEAK_BUNDLE"


class AssociationPhase(str, Enum):
    PRE_APPROVAL = "PRE_APPROVAL"
    DURING_BROADCAST = "DURING_BROADCAST"


class ProductAssociationStatus(str, Enum):
    PENDING_MATCH = "PENDING_MATCH"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SETTLED = "SETTLED"
    REFUNDED_FULL = "REFUNDED_FULL"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    WINDOW_OPEN = "WINDOW_OPEN"
    READY_FOR_PAYOUT = "READY_FOR_PAYOUT"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ViolationType(str, Enum):
    FALSE_ADVERTISING = "FALSE_ADVERTISING"
    WRONG_PRODUCT = "WRONG_PRODUCT"
    VIOLATING_CONTENT = "VIOLATING_CONTENT"
    DATA_FRAUD = "DATA_FRAUD"


class PenaltyAction(str, Enum):
    WARNING = "WARNING"
    FINE = "FINE"
    SUSPENSION = "SUSPENSION"
    BLACKLIST = "BLACKLIST"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    APPEAL_PENDING = "APPEAL_PENDING"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    ENFORCED = "ENFORCED"


class AppealDecision(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class ApprovalLevel(str, Enum):
    OPS = "OPS"
    COMPLIANCE = "COMPLIANCE"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class EventSource(str, Enum):
    PAYMENT = "PAYMENT"
    IM = "IM"
    ECOMMERCE = "ECOMMERCE"
    CONTENT_MOD = "CONTENT_MOD"


class EventKind(str, Enum):
    DEPOSIT_PAID = "DEPOSIT_PAID"
    DEPOSIT_REFUNDED = "DEPOSIT_REFUNDED"
    BROADCAST_GMV = "BROADCAST_GMV"
    RETURN_REPORTED = "RETURN_REPORTED"
    CONTENT_FLAGGED = "CONTENT_FLAGGED"
    IM_CHANNEL_OPENED = "IM_CHANNEL_OPENED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true -> carries id + created_at + updated_at + version
# common_fields: false -> append-only, carries only id + created_at


class Streamer(TypedDict, total=False):
    id: str
    legal_name: str
    id_card_number: str
    real_name_verified: bool
    health_cert_expires_at: str
    professional_cert_categories: List[str]
    content_category_tags: List[str]
    tier: str
    lifetime_gmv_cents: int
    completed_broadcast_count: int
    violation_score: int
    status: str
    suspension_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Studio(TypedDict, total=False):
    id: str
    name: str
    location: str
    equipment_inventory: List[str]
    capacity: int
    studio_type: str
    status: str
    slot_tier: str
    base_hour_price_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, NO updated_at, NO version
class TimeSlotConfig(TypedDict, total=False):
    id: str
    studio_id: str
    kind: str
    starts_at: str
    ends_at: str
    weekday_mask: int
    created_at: str


class ScheduleApplication(TypedDict, total=False):
    id: str
    streamer_id: str
    studio_id: str
    starts_at: str
    ends_at: str
    declared_content_categories: List[str]
    declared_product_categories: List[str]
    package_code: str
    review_status: str
    operational_status: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    deposit_cents: Optional[int]
    deposit_paid: bool
    pinned_streamer_tier: Optional[str]
    gmv_cents: int
    gross_commission_cents: int
    net_payout_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only
class ApprovalRecord(TypedDict, total=False):
    id: str
    application_id: str
    level: str
    decision: str
    reviewer_role: str
    reviewer_id: str
    reason: Optional[str]
    snapshot_streamer_tier: str
    snapshot_provisional_fee_cents: int
    created_at: str


class Product(TypedDict, total=False):
    id: str
    name: str
    category: str
    requires_professional_cert: bool
    unit_price_cents: int
    available_stock: int
    reserved_stock: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductAssociation(TypedDict, total=False):
    id: str
    application_id: str
    product_id: str
    reserved_quantity: int
    association_phase: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlotFeeInvoice(TypedDict, total=False):
    id: str
    application_id: str
    subtotal_cents: int
    peak_surcharge_cents: int
    package_discount_cents: int
    total_cents: int
    deposit_due_cents: int
    status: str
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionSettlement(TypedDict, total=False):
    id: str
    application_id: str
    gross_sales_cents: int
    returned_sales_cents: int
    commission_rate_bp: int
    tier_bonus_cents: int
    tax_withholding_cents: Optional[int]
    return_window_ends_at: str
    status: str
    provisional_payout_cents: int
    final_payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    streamer_id: str
    application_id: Optional[str]
    violation_type: str
    evidence_refs: List[str]
    severity: int
    penalty_action: str
    fine_cents: int
    suspension_days: int
    status: str
    enforced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    violation_id: str
    streamer_id: str
    argument: str
    decision: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only
class ExternalEvent(TypedDict, total=False):
    id: str
    source: str
    kind: str
    application_id: Optional[str]
    streamer_id: Optional[str]
    amount_cents: int
    occurred_at: str
    created_at: str


# common_fields: false — append-only
class AuditLog(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload_snapshot: Any
    created_at: str
