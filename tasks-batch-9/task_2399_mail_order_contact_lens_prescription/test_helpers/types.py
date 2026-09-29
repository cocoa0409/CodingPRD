"""Domain types for the mail-order contact lens platform.

Entity TypedDicts, lifecycle status enums and the caller role enum, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PRESCRIBER = "Prescriber"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FULFILLMENT_OPERATOR = "FulfillmentOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status / enum domains
# --------------------------------------------------------------------------


class InsurancePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class WearSchedule(str, Enum):
    DAILY_DISPOSABLE = "DAILY_DISPOSABLE"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class EquivalenceClass(str, Enum):
    EXACT = "EXACT"
    CLINICAL = "CLINICAL"
    MATERIAL_ONLY = "MATERIAL_ONLY"


class LensEquivalenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PrescriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ContactChannel(str, Enum):
    FAX = "FAX"
    PORTAL = "PORTAL"
    EMAIL = "EMAIL"


class CaptureMode(str, Enum):
    UPLOAD = "UPLOAD"
    DOCTOR_LOOKUP = "DOCTOR_LOOKUP"
    SELF_REPORT = "SELF_REPORT"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    VERIFIED_ACTIVE = "VERIFIED_ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class VerificationRequestStatus(str, Enum):
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    DENIED = "DENIED"
    PASSIVE_TIMEOUT = "PASSIVE_TIMEOUT"


class VerificationResponseType(str, Enum):
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    DENIED = "DENIED"


class OrderVerificationState(str, Enum):
    RX_PENDING = "RX_PENDING"
    RX_CLEARED = "RX_CLEARED"
    RX_BLOCKED = "RX_BLOCKED"


class OrderFulfillmentState(str, Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SubstitutionType(str, Enum):
    NONE = "NONE"
    BRAND_EQUIVALENT = "BRAND_EQUIVALENT"
    PARAMETER_ROUNDED = "PARAMETER_ROUNDED"


class CancellationReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    DISPUTE_UPHELD = "DISPUTE_UPHELD"
    PRESCRIBER_DENIED = "PRESCRIBER_DENIED"
    RX_EXPIRED = "RX_EXPIRED"


class ReorderHoldStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    ESCALATED = "ESCALATED"


class ReorderHoldReason(str, Enum):
    PRESCRIBER_DENIED = "PRESCRIBER_DENIED"
    PRESCRIPTION_EXPIRED = "PRESCRIPTION_EXPIRED"
    DISPUTE_UPHELD = "DISPUTE_UPHELD"
    MANUAL = "MANUAL"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CadenceBasis(str, Enum):
    NOMINAL = "NOMINAL"
    USAGE_ADJUSTED = "USAGE_ADJUSTED"


class PauseReason(str, Enum):
    HOLD_OPEN = "HOLD_OPEN"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    SKIP_LIMIT = "SKIP_LIMIT"


class ReturnRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class ReturnReason(str, Enum):
    TORN_LENS = "TORN_LENS"
    PRESCRIPTION_CHANGE = "PRESCRIPTION_CHANGE"
    WRONG_PARAMETER = "WRONG_PARAMETER"


class SettlementMode(str, Enum):
    PER_BOX_ROUNDED = "PER_BOX_ROUNDED"
    POOLED_ROUNDED = "POOLED_ROUNDED"
    NO_PRORATION = "NO_PRORATION"


class SettlementChannel(str, Enum):
    CASH_REFUND = "CASH_REFUND"
    STORE_CREDIT = "STORE_CREDIT"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class ClaimVoidedReason(str, Enum):
    DISPUTE_UPHELD = "DISPUTE_UPHELD"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    PLAN_RETIRED = "PLAN_RETIRED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class DisputeReason(str, Enum):
    NOT_MY_PATIENT = "NOT_MY_PATIENT"
    PARAMETERS_ALTERED = "PARAMETERS_ALTERED"
    NEVER_ISSUED = "NEVER_ISSUED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ComplianceEventType(str, Enum):
    RX_SUBMITTED = "RX_SUBMITTED"
    REQUEST_SENT = "REQUEST_SENT"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    PASSIVE_PROMOTED = "PASSIVE_PROMOTED"
    RX_EXPIRED = "RX_EXPIRED"
    RX_INVALIDATED = "RX_INVALIDATED"
    HOLD_OPENED = "HOLD_OPENED"
    HOLD_RELEASED = "HOLD_RELEASED"
    HOLD_ESCALATED = "HOLD_ESCALATED"
    ORDER_BLOCKED = "ORDER_BLOCKED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    SUBSTITUTION_APPLIED = "SUBSTITUTION_APPLIED"
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    CLAIM_VOIDED = "CLAIM_VOIDED"
    SCHEDULE_PAUSED = "SCHEDULE_PAUSED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class InsurancePlan(TypedDict):
    id: str
    name: str
    network_status: str
    annual_allowance_cents: int
    coinsurance_rate: float
    requires_itemized_receipt: bool
    covers_shipping: bool
    claim_window_days: int
    plan_year_start_month_day: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    brand: str
    name: str
    wear_schedule: str
    lenses_per_box: int
    unit_price_cents: int
    base_curve: float
    diameter: float
    sphere_min: float
    sphere_max: float
    sphere_step: float
    material_family: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LensEquivalence(TypedDict):
    id: str
    from_product_id: str
    to_product_id: str
    equivalence_class: str
    requires_patient_consent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict):
    id: str
    full_name: str
    license_number: str
    license_state: str
    contact_channel: str
    directory_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    insurance_plan_id: Optional[str]
    store_credit_cents: int
    lifetime_charged_cents: int
    lifetime_refunded_cents: int
    net_cash_position_cents: int
    allowance_used_cents: int
    open_hold_count: int
    active_schedule_count: int
    auto_reorder_enabled: bool
    created_at: str
    updated_at: str
    version: int


class CustomerLedger(TypedDict):
    customer_id: str
    lifetime_charged_cents: int
    lifetime_refunded_cents: int
    net_cash_position_cents: int
    store_credit_cents: int
    allowance_used_cents: int
    allowance_remaining_cents: int
    open_hold_count: int
    active_schedule_count: int
    auto_reorder_enabled: bool


class Prescription(TypedDict):
    id: str
    customer_id: str
    prescriber_id: Optional[str]
    product_id: str
    supersedes_prescription_id: Optional[str]
    capture_mode: str
    document_reference: Optional[str]
    self_reported_prescriber_name: Optional[str]
    issue_date: str
    expiry_date: str
    od_sphere: float
    os_sphere: float
    base_curve: float
    diameter: float
    boxes_authorized_total: int
    boxes_consumed: int
    verification_rounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict):
    id: str
    prescription_id: str
    prescriber_id: str
    channel: str
    sent_at: str
    passive_deadline_at: str
    round_number: int
    response_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    prescription_id: str
    ordered_product_id: str
    fulfilled_product_id: Optional[str]
    boxes_od: int
    boxes_os: int
    unit_price_cents: int
    lenses_per_box_at_capture: int
    subtotal_cents: int
    shipping_cents: int
    total_cents: int
    verification_state: str
    fulfillment_state: str
    substitution_type: str
    parameter_deviation_index: float
    fulfilled_od_sphere: Optional[float]
    fulfilled_os_sphere: Optional[float]
    itemized_receipt_reference: Optional[str]
    recall_flagged: bool
    cancellation_reason: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReorderHold(TypedDict):
    id: str
    customer_id: str
    prescription_id: str
    reason: str
    opened_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    escalated_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AutoReorderSchedule(TypedDict):
    id: str
    customer_id: str
    prescription_id: str
    product_id: str
    boxes_per_run: int
    cadence_basis: str
    observed_days_per_box: Optional[int]
    cadence_days: int
    anchor_date: str
    next_run_at: str
    consecutive_skip_count: int
    pause_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    order_id: str
    customer_id: str
    reason: str
    unopened_boxes: int
    opened_box_used_counts: List[int]
    torn_lens_count: Optional[int]
    settlement_mode: str
    settlement_cents: int
    settlement_channel: str
    approved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    order_id: str
    customer_id: str
    insurance_plan_id: str
    refund_offset_cents: int
    base_eligible_cents: Optional[int]
    applied_allowance_cents: Optional[int]
    coinsurance_cents: Optional[int]
    pre_fee_subtotal_cents: Optional[int]
    processing_fee_cents: Optional[int]
    reimbursable_cents: Optional[int]
    packet_reference: Optional[str]
    submitted_at: Optional[str]
    voided_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrescriberDispute(TypedDict):
    id: str
    prescription_id: str
    prescriber_id: str
    dispute_reason: str
    resolution: Optional[str]
    resolved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceEvent(TypedDict):
    """Append-only audit row: carries id and created_at only — no version,
    no updated_at."""

    id: str
    prescription_id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_role: Optional[str]
    actor_user_id: Optional[str]
    detail: Optional[str]
    occurred_at: str
    created_at: str


class VerificationSweepResult(TypedDict):
    promoted_prescription_ids: List[str]
    timed_out_request_ids: List[str]
    expired_prescription_ids: List[str]
    holds_opened_count: int
    schedules_paused_count: int


class AutoReorderRunResult(TypedDict):
    run_at: str
    shipped_order_ids: List[str]
    skipped_schedule_ids: List[str]
    paused_schedule_ids: List[str]
