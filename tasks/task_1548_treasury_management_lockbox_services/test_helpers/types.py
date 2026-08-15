"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — spelled exactly as in the PRD)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    BANK_OPERATIONS_ADMIN = "BankOperationsAdmin"
    TREASURY_IMPLEMENTER = "TreasuryImplementer"
    TREASURY_ACTIVATOR = "TreasuryActivator"
    LOCKBOX_OPERATOR = "LockboxOperator"
    CUSTOMER_OPERATOR = "CustomerOperator"
    BILLING_SPECIALIST = "BillingSpecialist"
    BILLING_APPROVER = "BillingApprover"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status / kind enums (PRD §3 narratives)
# ---------------------------------------------------------------------------

class BankPosture(str, Enum):
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    LIQUIDATING = "LIQUIDATING"


class CustomerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    IMPLEMENTED = "IMPLEMENTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SiteStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FormatKind(str, Enum):
    BAI2 = "BAI2"
    EDI820 = "EDI820"
    CUSTOM_CSV = "CUSTOM_CSV"


class TransmissionFormatStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CaptureStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CAPTURING = "CAPTURING"
    BALANCED = "BALANCED"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"
    CLOSED = "CLOSED"


class TransmissionStatus(str, Enum):
    PENDING = "PENDING"
    TRANSMITTED = "TRANSMITTED"
    TRANSMISSION_FAILED = "TRANSMISSION_FAILED"
    ACKED = "ACKED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    DECISIONS_PENDING = "DECISIONS_PENDING"
    READY_TO_SETTLE = "READY_TO_SETTLE"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class ItemStatus(str, Enum):
    CAPTURED = "CAPTURED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    ON_EXCEPTION = "ON_EXCEPTION"
    DECISIONED_PAY = "DECISIONED_PAY"
    DECISIONED_RETURN = "DECISIONED_RETURN"


class AvailabilityTier(str, Enum):
    SAME_DAY = "SAME_DAY"
    ONE_DAY = "ONE_DAY"
    TWO_DAY = "TWO_DAY"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ExceptionReasonCode(str, Enum):
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    MISSING_INVOICE_REF = "MISSING_INVOICE_REF"
    STALE_DATED = "STALE_DATED"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"


class ExceptionDecision(str, Enum):
    PAY = "PAY"
    RETURN = "RETURN"


class ExceptionStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    AUTO_DECISIONED = "AUTO_DECISIONED"
    ESCALATED = "ESCALATED"


class ImageRequestReason(str, Enum):
    AUDIT = "AUDIT"
    DISPUTE_SUPPORT = "DISPUTE_SUPPORT"
    RESEARCH = "RESEARCH"
    LEGAL = "LEGAL"


class ImageKind(str, Enum):
    CHECK_FRONT = "CHECK_FRONT"
    CHECK_BACK = "CHECK_BACK"
    REMIT_STUB = "REMIT_STUB"
    ENVELOPE = "ENVELOPE"


class ImageRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class LineKind(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    PER_ITEM_CAPTURE = "PER_ITEM_CAPTURE"
    PER_EXCEPTION_DECISION = "PER_EXCEPTION_DECISION"
    PER_IMAGE_RETRIEVAL = "PER_IMAGE_RETRIEVAL"
    SLA_CREDIT = "SLA_CREDIT"


class IncidentKind(str, Enum):
    LATE_TRANSMISSION = "LATE_TRANSMISSION"
    LATE_IMAGE_FULFILLMENT = "LATE_IMAGE_FULFILLMENT"
    MISSED_CUTOFF_POSTING = "MISSED_CUTOFF_POSTING"
    DATA_FORMAT_ERROR = "DATA_FORMAT_ERROR"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class CreditReasonCode(str, Enum):
    SLA_NOT_APPLIED = "SLA_NOT_APPLIED"
    BILLING_RATE_ERROR = "BILLING_RATE_ERROR"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    ECR_MISCALCULATION = "ECR_MISCALCULATION"


class CreditRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# (PRD §2.4 common resource properties)
# ---------------------------------------------------------------------------

class Bank(TypedDict, total=False):
    id: str
    legal_name: str
    routing_number: str
    current_business_date: str
    current_analysis_cycle_index: int
    default_earnings_credit_rate_bp: int
    sla_credit_breach_threshold_bp: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    bank_id: str
    legal_name: str
    tax_id: str
    status: str
    deposit_account_number: str
    average_collected_balance_cents: int
    collected_balance_accumulator_cents: int
    days_in_cycle_elapsed: int
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    bank_id: str
    agreement_number: str
    earnings_credit_rate_bp: Optional[int]
    ecr_override_allowed: bool
    monthly_maintenance_fee_cents: int
    per_item_capture_fee_cents: int
    per_exception_decision_fee_cents: int
    per_image_retrieval_fee_cents: int
    implemented_by_user_id: str
    activated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LockboxSite(TypedDict, total=False):
    id: str
    agreement_id: str
    customer_id: str
    bank_id: str
    site_code: str
    postal_box_address: str
    daily_cutoff_time_local: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransmissionFormat(TypedDict, total=False):
    id: str
    agreement_id: str
    customer_id: str
    bank_id: str
    format_kind: str
    version_label: str
    supersedes_format_id: Optional[str]
    include_invoice_detail: bool
    include_images: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceBatch(TypedDict, total=False):
    id: str
    site_id: str
    agreement_id: str
    customer_id: str
    bank_id: str
    batch_reference: str
    business_date: str
    received_at: str
    declared_item_count: int
    declared_total_cents: int
    captured_item_count: int
    captured_total_cents: int
    accepted_item_count: int
    accepted_total_cents: int
    same_day_credit_cents: int
    capture_status: str
    transmission_status: str
    batch_status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceItem(TypedDict, total=False):
    id: str
    batch_id: str
    site_id: str
    customer_id: str
    bank_id: str
    check_number: str
    payer_routing_number: str
    amount_cents: int
    payee_name: str
    invoice_reference: Optional[str]
    availability_tier: str
    availability_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilitySchedule(TypedDict, total=False):
    id: str
    site_id: str
    bank_id: str
    routing_number_pattern: str
    tier: str
    effective_from: str
    effective_to: Optional[str]
    priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionItem(TypedDict, total=False):
    id: str
    item_id: str
    batch_id: str
    customer_id: str
    bank_id: str
    reason_code: str
    default_decision: str
    auto_decision_at: str
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImageRetrievalRequest(TypedDict, total=False):
    id: str
    customer_id: str
    bank_id: str
    item_id: str
    request_reason: str
    requested_image_kinds: List[str]
    fulfillment_uri: Optional[str]
    retention_expires_at: str
    sla_due_at: str
    fulfilled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalysisCycle(TypedDict, total=False):
    id: str
    customer_id: str
    bank_id: str
    agreement_id: str
    cycle_index: int
    cycle_start_date: str
    cycle_end_date: str
    average_collected_balance_cents: int
    gross_service_charges_cents: int
    earnings_credit_cents: int
    net_amount_due_cents: int
    accepted_item_count: int
    exception_decision_count: int
    image_retrieval_fulfilled_count: int
    sla_error_count: int
    sla_error_rate_bp: int
    sla_breach: bool
    sla_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalysisLineItem(TypedDict, total=False):
    id: str
    cycle_id: str
    bank_id: str
    line_kind: str
    quantity: int
    unit_price_cents: int
    extended_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SLAIncident(TypedDict, total=False):
    id: str
    customer_id: str
    bank_id: str
    cycle_id: Optional[str]
    incident_kind: str
    reference_batch_id: Optional[str]
    reference_request_id: Optional[str]
    occurred_on_business_date: str
    breach_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ErrorCreditRequest(TypedDict, total=False):
    id: str
    customer_id: str
    bank_id: str
    cycle_id: str
    requested_credit_cents: int
    reason_code: str
    approved_credit_cents: Optional[int]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
