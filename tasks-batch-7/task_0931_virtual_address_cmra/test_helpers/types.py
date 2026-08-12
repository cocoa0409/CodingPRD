"""Domain types for the Virtual-Address & Mail-Scanning (CMRA) API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CMRA_OPERATOR = "CmraOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    NOTARY = "Notary"
    BOX_HOLDER = "BoxHolder"
    RECIPIENT = "Recipient"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class TierCode(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class CarrierCode(str, Enum):
    USPS = "USPS"
    UPS = "UPS"
    FEDEX = "FEDEX"
    DHL = "DHL"
    AMAZON = "AMAZON"


class BoxServiceStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class BoxComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    NON_COMPLIANT = "NON_COMPLIANT"


class SuspendedReason(str, Enum):
    NONE = "NONE"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    USPS_ORDER = "USPS_ORDER"


class ReleaseGateState(str, Enum):
    OPEN = "OPEN"
    GATED_SUSPENDED = "GATED_SUSPENDED"
    GATED_LIFECYCLE = "GATED_LIFECYCLE"


class RecipientKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"
    MINOR = "MINOR"


class RosterStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ReleaseEligibility(str, Enum):
    BLOCKED = "BLOCKED"
    RELEASABLE = "RELEASABLE"


class BlockedReason(str, Enum):
    NONE = "NONE"
    NO_ACCEPTED_1583 = "NO_ACCEPTED_1583"
    ID_SET_INCOMPLETE = "ID_SET_INCOMPLETE"
    ID_EXPIRED = "ID_EXPIRED"
    GUARANTOR_BLOCKED = "GUARANTOR_BLOCKED"
    ROSTER_NOT_AUTHORIZED = "ROSTER_NOT_AUTHORIZED"


class Form1583Status(str, Enum):
    DRAFT = "DRAFT"
    NOTARIZED = "NOTARIZED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RejectionReason(str, Enum):
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    ILLEGIBLE = "ILLEGIBLE"
    NAME_MISMATCH = "NAME_MISMATCH"
    INCOMPLETE_ID = "INCOMPLETE_ID"


class DocClass(str, Enum):
    PHOTO = "PHOTO"
    ADDRESS = "ADDRESS"


class DocType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"
    UTILITY_BILL = "UTILITY_BILL"
    LEASE = "LEASE"
    VOTER_CARD = "VOTER_CARD"
    VEHICLE_REGISTRATION = "VEHICLE_REGISTRATION"


class IdDocumentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ItemClass(str, Enum):
    LETTER = "LETTER"
    FLAT = "FLAT"
    PACKAGE = "PACKAGE"
    SOP = "SOP"


class HandlingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AWAITING_CLEARANCE = "AWAITING_CLEARANCE"
    HELD = "HELD"
    PENDING_DISPOSITION = "PENDING_DISPOSITION"
    FORWARDED = "FORWARDED"
    SHREDDED = "SHREDDED"
    DEPOSITED = "DEPOSITED"
    RETURNED = "RETURNED"
    REFUSED = "REFUSED"


class StorageStatus(str, Enum):
    FREE_WINDOW = "FREE_WINDOW"
    ACCRUING = "ACCRUING"
    RELEASED = "RELEASED"
    DESTROYED = "DESTROYED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    METERED = "METERED"
    BILLED = "BILLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class NotificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SENT = "SENT"
    BREACHED = "BREACHED"


class RefusalReason(str, Enum):
    NOT_ON_ROSTER = "NOT_ON_ROSTER"
    OVERSIZE = "OVERSIZE"
    CARRIER_NOT_ACCEPTED = "CARRIER_NOT_ACCEPTED"
    HOLDER_REQUEST = "HOLDER_REQUEST"


class ScanTier(str, Enum):
    COVER = "COVER"
    INTERIOR = "INTERIOR"
    OCR = "OCR"


class ScanJobStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class DispositionType(str, Enum):
    FORWARD = "FORWARD"
    SHRED = "SHRED"
    DEPOSIT = "DEPOSIT"
    RETURN = "RETURN"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ResolutionReason(str, Enum):
    NONE = "NONE"
    EXECUTED = "EXECUTED"
    LOST_PRECEDENCE = "LOST_PRECEDENCE"
    GATE_SUSPENSION = "GATE_SUSPENSION"
    HOLDER_CANCELLED = "HOLDER_CANCELLED"


class ServiceLevel(str, Enum):
    ECONOMY = "ECONOMY"
    PRIORITY = "PRIORITY"
    EXPRESS = "EXPRESS"


class ForwardShipmentStatus(str, Enum):
    PRICED = "PRICED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class MatchMode(str, Enum):
    NONE = "NONE"
    EXACT_LEGAL = "EXACT_LEGAL"
    ALIAS = "ALIAS"


class CheckDepositStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHED = "MATCHED"
    DEPOSITED = "DEPOSITED"
    HELD = "HELD"
    RETURNED = "RETURNED"


class HoldReason(str, Enum):
    NONE = "NONE"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    NOT_ENDORSED = "NOT_ENDORSED"


class DepositBatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ComplianceReviewReason(str, Enum):
    ID_EXPIRY = "ID_EXPIRY"
    USPS_AUDIT = "USPS_AUDIT"
    ROSTER_ANOMALY = "ROSTER_ANOMALY"
    PAYMENT = "PAYMENT"


class ComplianceReviewStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    RESOLVED = "RESOLVED"


class ComplianceResolution(str, Enum):
    NONE = "NONE"
    CLEARED = "CLEARED"
    ESCALATED_CLOSURE = "ESCALATED_CLOSURE"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class UnitType(str, Enum):
    SCAN_PAGE = "SCAN_PAGE"
    FORWARD = "FORWARD"
    STORAGE_DAY = "STORAGE_DAY"
    RECIPIENT = "RECIPIENT"


class Tranche(str, Enum):
    IN_TIER = "IN_TIER"
    OVERAGE = "OVERAGE"


class SourceEvent(str, Enum):
    SCAN_COMPLETED = "SCAN_COMPLETED"
    FORWARD_SHIPPED = "FORWARD_SHIPPED"
    STORAGE_ACCRUAL = "STORAGE_ACCRUAL"
    RECIPIENT_AUTHORIZED = "RECIPIENT_AUTHORIZED"
    PLAN_CHANGE = "PLAN_CHANGE"


class CancellationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FINAL_FORWARD = "FINAL_FORWARD"
    FINALIZED = "FINALIZED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Entity shapes
#
# A plan tier, a carrier rule and a usage-ledger entry carry only `id` and
# `created_at` (PRD §2.4); every other resource additionally carries
# `updated_at` and `version`.
# --------------------------------------------------------------------------
class PlanTier(TypedDict):
    id: str
    created_at: str
    tier_code: str
    name: str
    rank: int
    monthly_fee_cents: int
    included_recipients: int
    included_scan_pages: int
    included_forwards: int
    included_storage_days: int
    overage_scan_page_cents: int
    overage_forward_cents: int
    overage_storage_day_cents: int
    overage_recipient_cents: int
    allows_overage: bool


class CarrierRule(TypedDict):
    id: str
    created_at: str
    carrier_code: str
    dim_divisor: int
    max_length_plus_girth_in: float
    max_actual_weight_lb: float
    accepts_signature_required: bool
    acceptance_fee_cents: int
    base_rate_cents_per_lb: int


class UsageLedgerEntry(TypedDict):
    id: str
    created_at: str
    billing_cycle_id: str
    mail_item_id: Optional[str]
    unit_type: str
    tranche: str
    quantity: int
    unit_rate_cents: int
    amount_cents: int
    source_event: str


class Box(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_number: str
    plan_tier_id: str
    pending_plan_tier_id: Optional[str]
    holder_name: str
    holder_email: str
    security_deposit_cents: int
    extra_recipient_slots: int
    prepaid_balance_cents: int
    service_status: str
    compliance_status: str
    suspended_reason: str
    activated_at: Optional[str]
    cycle_anchor_date: Optional[str]
    outstanding_overage_cents: int
    roster_authorized_count: int
    release_gate_state: str


class Recipient(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    legal_name: str
    recipient_kind: str
    dba_aliases: List[str]
    guarantor_recipient_id: Optional[str]
    signature_authorization_on_file: bool
    roster_status: str
    release_eligibility: str
    blocked_reason: str
    form_1583_accepted_at: Optional[str]


class Form1583(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    recipient_id: str
    home_address_line: str
    status: str
    notarized_at: Optional[str]
    notary_user_id: Optional[str]
    accepted_on: Optional[str]
    expires_on: Optional[str]
    accepted_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class IdDocument(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    recipient_id: str
    doc_class: str
    doc_type: str
    expires_on: str
    status: str
    verified_at: Optional[str]


class MailItem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    addressee_name: str
    matched_recipient_id: Optional[str]
    item_class: str
    carrier_rule_id: Optional[str]
    signature_required: bool
    actual_weight_lb: float
    length_in: float
    width_in: float
    height_in: float
    received_at: str
    accepted_at: Optional[str]
    released_at: Optional[str]
    handling_status: str
    storage_status: str
    billing_status: str
    notification_status: str
    notification_due_at: Optional[str]
    notified_at: Optional[str]
    interior_scan_consent: bool
    forward_shipment_id: Optional[str]
    billable_weight_lb: float
    package_acceptance_fee_cents: int
    free_storage_days_used: int
    billable_storage_days: int
    refusal_reason: Optional[str]


class ScanJob(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    mail_item_id: str
    scan_tier: str
    requested_pages: int
    split_index: int
    split_group_size: int
    page_count: int
    status: str
    retry_count: int
    billed_pages_in_tier: Optional[int]
    billed_pages_overage: Optional[int]
    charge_cents: Optional[int]


class DispositionRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    mail_item_id: str
    disposition_type: str
    precedence_rank: int
    status: str
    resolution_reason: str
    executed_at: Optional[str]


class ForwardShipment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    service_level: str
    destination_address: str
    status: str
    item_count: int
    excluded_item_count: int
    total_weight_lb: float
    base_price_cents: int
    consolidation_discount_cents: int
    total_price_cents: int
    shipped_at: Optional[str]


class CheckDeposit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    mail_item_id: str
    deposit_batch_id: str
    matched_recipient_id: Optional[str]
    payee_name_on_check: str
    amount_cents: int
    endorsed: bool
    match_mode: str
    status: str
    hold_reason: str


class DepositBatch(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    business_date: str
    closed: bool
    closed_at: Optional[str]
    status: str
    check_count: int
    received_amount_cents: int
    deposited_amount_cents: int
    returned_amount_cents: int
    held_amount_cents: int


class RegisteredAgentService(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    jurisdiction_code: str
    retention_days: int
    active: bool
    deactivated_at: Optional[str]
    sop_count: int


class ComplianceReview(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    reason: str
    status: str
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolution: str
    resolved_at: Optional[str]


class BillingCycle(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    cycle_index: int
    period_start: str
    period_end: str
    status: str
    plan_tier_id_at_close: Optional[str]
    scan_pages_consumed: int
    forwards_consumed: int
    storage_days_consumed: int
    recipients_consumed: int
    base_fee_cents: int
    overage_total_cents: int
    proration_charge_cents: int
    proration_credit_cents: int
    loyalty_discount_cents: int
    total_charge_cents: int


class CancellationRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    box_id: str
    forwarding_address: str
    requested_on: str
    notice_end_date: str
    final_forward_deadline: str
    abandonment_date: str
    destruction_eligible_on: str
    status: str
    prepaid_at_request_cents: int
    deposit_held_cents: int
    applied_to_overage_cents: int
    refund_total_cents: int
    forfeited_cents: int
