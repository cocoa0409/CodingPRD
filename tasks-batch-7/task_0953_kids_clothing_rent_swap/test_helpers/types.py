"""Domain types: status enums, role enum and entity TypedDicts.

All twenty-one persisted entity types carry `updated_at` and an integer
`version` (PRD 2.4: "No entity in this system is exempt from updated_at or
version"), so every TypedDict below lists them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MEMBER = "Member"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    GRADING_TECHNICIAN = "GradingTechnician"
    CLEANING_VENDOR = "CleaningVendor"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    BILLING_AGENT = "BillingAgent"
    MERCHANDISE_PLANNER = "MerchandisePlanner"


class PlanTier(str, Enum):
    STARTER = "STARTER"
    CORE = "CORE"
    PLUS = "PLUS"
    CAPSULE_PLUS = "CAPSULE_PLUS"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELINQUENT = "DELINQUENT"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SWAP_CLOSED = "SWAP_CLOSED"
    RETURN_DUE = "RETURN_DUE"
    GRACE = "GRACE"
    HELD = "HELD"
    CLOSED = "CLOSED"
    DELINQUENT_CLOSED = "DELINQUENT_CLOSED"


class GarmentStyleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class BrandTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    VALUE = "VALUE"


class Season(str, Enum):
    SS = "SS"
    AW = "AW"
    ALL_SEASON = "ALL_SEASON"


class DemandBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GarmentUnitState(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    OUT = "OUT"
    INBOUND = "INBOUND"
    PROCESSING = "PROCESSING"
    LOST_IN_TRANSIT = "LOST_IN_TRANSIT"
    RETIRED = "RETIRED"
    SOLD = "SOLD"


class AcquisitionSource(str, Enum):
    PURCHASED = "PURCHASED"
    TRADE_IN_ABSORBED = "TRADE_IN_ABSORBED"


class RetiredReason(str, Enum):
    CYCLE_CAP = "CYCLE_CAP"
    COST_CAP = "COST_CAP"
    GRADE_RETIRE = "GRADE_RETIRE"
    REWORK_FAILED = "REWORK_FAILED"
    LOST_WRITE_OFF = "LOST_WRITE_OFF"


class BoxStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURN_STARTED = "RETURN_STARTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BoxItemFulfillmentStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    WITH_MEMBER = "WITH_MEMBER"
    RETURNING = "RETURNING"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


class BoxItemSettlementStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"
    BOUGHT_OUT = "BOUGHT_OUT"
    LOST_CHARGED = "LOST_CHARGED"


class SwapRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SwapRejectionReason(str, Enum):
    NO_ELIGIBLE_STOCK = "NO_ELIGIBLE_STOCK"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    EMBARGOED_ITEM = "EMBARGOED_ITEM"
    MEMBER_STANDING = "MEMBER_STANDING"


class ShipmentDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"
    TRADE_IN_INBOUND = "TRADE_IN_INBOUND"
    REJECT_RETURN = "REJECT_RETURN"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    RETURNED_TO_SENDER = "RETURNED_TO_SENDER"


class ShippingLabelStatus(str, Enum):
    ISSUED = "ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class AssessmentPipeline(str, Enum):
    RENTAL = "RENTAL"
    TRADE_IN = "TRADE_IN"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    RETIRE = "RETIRE"


class ConditionAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class ProcessingRoute(str, Enum):
    STANDARD_LAUNDER = "STANDARD_LAUNDER"
    STAIN_TREATMENT = "STAIN_TREATMENT"
    REPAIR = "REPAIR"
    RETIRE = "RETIRE"


class ProcessingJobStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    PASSED = "PASSED"
    SCRAPPED = "SCRAPPED"


class TradeInSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    LABEL_ISSUED = "LABEL_ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    GRADING = "GRADING"
    CREDITED = "CREDITED"
    CLOSED = "CLOSED"


class TradeInGradingStatus(str, Enum):
    PENDING = "PENDING"
    GRADED = "GRADED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class TradeInDispositionStatus(str, Enum):
    NONE = "NONE"
    AWAITING_ELECTION = "AWAITING_ELECTION"
    ABSORBED = "ABSORBED"
    RETURN_TO_MEMBER = "RETURN_TO_MEMBER"
    DONATE = "DONATE"
    RECYCLE = "RECYCLE"


class BuyOutOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BuyOutQuoteVariant(str, Enum):
    CYCLES_WORN = "CYCLES_WORN"
    MONTHS_HELD = "MONTHS_HELD"


class CapsuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    OPEN = "OPEN"
    EMBARGO_LIFTED = "EMBARGO_LIFTED"
    CLOSED = "CLOSED"


class CapsuleAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PauseRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    DENIED = "DENIED"


class PauseDenialReason(str, Enum):
    SHIPMENT_IN_TRANSIT = "SHIPMENT_IN_TRANSIT"
    UNIT_PAST_DUE = "UNIT_PAST_DUE"
    PERIOD_CAP = "PERIOD_CAP"
    LIFETIME_CAP = "LIFETIME_CAP"


class LostShipmentClaimStatus(str, Enum):
    OPENED = "OPENED"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_MEMBER_INFO = "AWAITING_MEMBER_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class LostClaimVariant(str, Enum):
    SCANNED = "SCANNED"
    NEVER_SCANNED = "NEVER_SCANNED"


class ChargeType(str, Enum):
    PLAN_CHARGE = "PLAN_CHARGE"
    PROTECTION_FEE = "PROTECTION_FEE"
    LATE_FEE = "LATE_FEE"
    DAMAGE_FEE = "DAMAGE_FEE"
    SHIPPING_FEE = "SHIPPING_FEE"
    LOST_LIABILITY = "LOST_LIABILITY"
    BUYOUT_PRICE = "BUYOUT_PRICE"
    SURCHARGE = "SURCHARGE"


class ChargeEntryStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class CreditEntryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProrationBasis(str, Enum):
    THIRTY_DAY = "THIRTY_DAY"
    ACTUAL_DAYS = "ACTUAL_DAYS"


class LateFeeMode(str, Enum):
    PER_DAY = "PER_DAY"
    FLAT_TIER = "FLAT_TIER"


# --------------------------------------------------------------------------
# Entity shapes (every entity carries id / created_at / updated_at / version)
# --------------------------------------------------------------------------


class Plan(TypedDict, total=False):
    id: str
    tier: str
    slots_per_box: int
    swaps_per_cycle: int
    monthly_fee_cents: int
    protection_available: bool
    proration_basis: str
    late_fee_mode: str
    capsule_quota_per_wave: int
    discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    plan_id: str
    email: str
    display_name: str
    child_size_code: str
    size_effective_at: str
    protection_enrolled: bool
    auto_apply_credit: bool
    status: str
    credit_balance_cents: int
    outstanding_balance_cents: int
    completed_cycles: int
    pause_days_used_period: int
    pause_days_used_lifetime: int
    total_paused_days: int
    permanent_slots_consumed: int
    created_at: str
    updated_at: str
    version: int


class Cycle(TypedDict, total=False):
    id: str
    member_id: str
    cycle_index: int
    start_at: str
    swap_by_at: str
    return_due_at: str
    grace_ends_at: str
    status: str
    plan_charge_cents: int
    proration_credit_cents: int
    discount_cents: int
    protection_fee_cents: int
    late_fee_cents: int
    damage_fee_cents: int
    credit_applied_cents: int
    surcharge_cents: int
    invoice_total_cents: int
    swaps_used: int
    slots_occupied: int
    paused_days: int
    protection_waiver_used_cents: int
    created_at: str
    updated_at: str
    version: int


class GarmentStyle(TypedDict, total=False):
    id: str
    sku: str
    name: str
    brand_tier: str
    retail_price_cents: int
    size_code: str
    season: str
    category: str
    demand_band: str
    units_ever_acquired: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GarmentUnit(TypedDict, total=False):
    id: str
    style_id: str
    capsule_id: Optional[str]
    state: str
    acquisition_source: str
    current_grade: str
    cycles_completed: int
    cumulative_cleaning_cost_cents: int
    retirement_eligible: bool
    retired_reason: Optional[str]
    acquired_at: str
    created_at: str
    updated_at: str
    version: int


class Box(TypedDict, total=False):
    id: str
    cycle_id: str
    member_id: str
    slot_capacity: int
    slots_free: int
    outbound_shipment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxItem(TypedDict, total=False):
    id: str
    box_id: str
    unit_id: str
    slot_index: int
    fulfillment_status: str
    settlement_status: str
    is_capsule_item: bool
    embargo_until: Optional[str]
    return_shipment_id: Optional[str]
    days_late: int
    late_fee_cents: int
    damage_fee_cents: int
    assessed_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SwapRequest(TypedDict, total=False):
    id: str
    cycle_id: str
    member_id: str
    return_box_item_ids: List[str]
    requested_style_ids: List[str]
    allocated_unit_ids: List[str]
    slot_delta: int
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShippingLabel(TypedDict, total=False):
    id: str
    member_id: str
    direction: str
    tracking_code: str
    issued_at: str
    expires_at: str
    reissue_count: int
    replaces_label_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    member_id: str
    label_id: str
    direction: str
    item_count: int
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    ever_scanned: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionAssessment(TypedDict, total=False):
    id: str
    pipeline: str
    unit_id: Optional[str]
    trade_in_item_id: Optional[str]
    grade: Optional[str]
    defect_codes: List[str]
    regrade_count: int
    graded_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingJob(TypedDict, total=False):
    id: str
    assessment_id: str
    unit_id: str
    route: str
    attempt_count: int
    cost_cents: int
    post_repair_grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInSubmission(TypedDict, total=False):
    id: str
    member_id: str
    declared_item_count: int
    inbound_shipment_id: Optional[str]
    credited_total_cents: int
    uncapped_total_cents: int
    election_deadline_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInItem(TypedDict, total=False):
    id: str
    submission_id: str
    declared_brand_tier: str
    declared_size_code: str
    assessed_grade: Optional[str]
    demand_band: str
    credit_cents: int
    granted_credit_cents: int
    absorbed_unit_id: Optional[str]
    grading_status: str
    disposition_status: str
    created_at: str
    updated_at: str
    version: int


class BuyOutOrder(TypedDict, total=False):
    id: str
    box_item_id: str
    member_id: str
    quote_variant: str
    quoted_price_cents: int
    late_surcharge_cents: int
    final_price_cents: int
    quoted_at: str
    quote_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Capsule(TypedDict, total=False):
    id: str
    season: str
    name: str
    release_at: str
    close_at: str
    embargo_until: Optional[str]
    quota_per_member: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapsuleAllocation(TypedDict, total=False):
    id: str
    capsule_id: str
    member_id: str
    units_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PauseRequest(TypedDict, total=False):
    id: str
    member_id: str
    start_at: str
    end_at: str
    days_requested: int
    proration_credit_cents: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LostShipmentClaim(TypedDict, total=False):
    id: str
    shipment_id: str
    member_id: str
    variant: Optional[str]
    assessed_value_cents: int
    member_liability_pct: float
    member_liability_cents: int
    filed_at: str
    deadline_at: str
    info_note: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    cycle_id: Optional[str]
    charge_type: str
    amount_cents: int
    credit_applied_cents: int
    net_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    source_submission_id: Optional[str]
    amount_cents: int
    remaining_cents: int
    granted_at: str
    expires_at: str
    paused_days_extension: int
    revoke_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
