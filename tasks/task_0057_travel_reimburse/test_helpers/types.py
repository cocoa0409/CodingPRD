"""Domain types for the Travel Reimburse API.

Entity TypedDicts, status enums, role enum. Per PRD §2.4: most resources
carry id + created_at + updated_at + version; ExpenseStandard,
ApprovalRecord, and AuditLog are write-once history rows and carry only
id + created_at.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    SUPERVISOR = "Supervisor"
    DEPT_HEAD = "DeptHead"
    FINANCE = "Finance"
    GENERAL_MANAGER = "GeneralManager"
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EmployeeLevel(str, Enum):
    STAFF = "STAFF"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    EXECUTIVE = "EXECUTIVE"


class CityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    OVERSEAS = "OVERSEAS"


class TravelScope(str, Enum):
    DOMESTIC = "DOMESTIC"
    OVERSEAS = "OVERSEAS"


class TravelApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERVISOR_APPROVED = "SUPERVISOR_APPROVED"
    DEPT_HEAD_APPROVED = "DEPT_HEAD_APPROVED"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    GM_APPROVED = "GM_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BOOKING_LOCKED = "BOOKING_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SegmentType(str, Enum):
    FLIGHT = "FLIGHT"
    TRAIN = "TRAIN"
    HOTEL = "HOTEL"
    CAR = "CAR"


class SegmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHANGED = "CHANGED"
    CANCELLED = "CANCELLED"


class InvoiceCategory(str, Enum):
    LODGING = "LODGING"
    PER_DIEM = "PER_DIEM"
    TRANSPORTATION = "TRANSPORTATION"
    OTHER = "OTHER"


class InvoiceOcrStatus(str, Enum):
    PENDING_OCR = "PENDING_OCR"
    OCR_RECOGNIZED = "OCR_RECOGNIZED"
    TAX_VERIFIED = "TAX_VERIFIED"
    REJECTED = "REJECTED"
    ATTACHED = "ATTACHED"
    CONSUMED = "CONSUMED"


class ReimbursementFormStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERVISOR_APPROVED = "SUPERVISOR_APPROVED"
    DEPT_APPROVED = "DEPT_APPROVED"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    GM_APPROVED = "GM_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class PaymentChannel(str, Enum):
    BANK_TRANSFER = "BANK_TRANSFER"
    CORPORATE_CARD_REFUND = "CORPORATE_CARD_REFUND"
    INTERNAL_WALLET = "INTERNAL_WALLET"


class PaymentOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class TaxVerifyVerdict(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class ApprovalAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ApprovalActorRole(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    DEPT_HEAD = "DEPT_HEAD"
    FINANCE = "FINANCE"
    GM = "GM"


class ApprovalSubjectType(str, Enum):
    TRAVEL_APPLICATION = "TRAVEL_APPLICATION"
    REIMBURSEMENT_FORM = "REIMBURSEMENT_FORM"


class AuditEventType(str, Enum):
    APPROVAL_ACTION = "APPROVAL_ACTION"
    PAYMENT_EVENT = "PAYMENT_EVENT"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


class AuditSubjectType(str, Enum):
    TRAVEL_APPLICATION = "TRAVEL_APPLICATION"
    REIMBURSEMENT_FORM = "REIMBURSEMENT_FORM"
    PAYMENT = "PAYMENT"
    INVOICE = "INVOICE"


# ---------------------------------------------------------------------------
# Approval-chain step constants (PRD §3.2)
# ---------------------------------------------------------------------------
CHAIN_STEP_SUPERVISOR = "SUPERVISOR"
CHAIN_STEP_DEPT_HEAD = "DEPT_HEAD"
CHAIN_STEP_FINANCE = "FINANCE"
CHAIN_STEP_GM = "GM"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# common_fields: true — carries id + created_at + updated_at + version
class Employee(TypedDict, total=False):
    id: str
    full_name: str
    employee_level: str
    department_id: str
    supervisor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once history row (PRD §2.4)
class ExpenseStandard(TypedDict, total=False):
    id: str
    version: int
    effective_from: str
    effective_to: Optional[str]
    city_tier: str
    employee_level: str
    lodging_daily_cap: float
    per_diem_amount: float
    transportation_daily_cap: float
    holiday_multiplier: float
    created_at: str


class TravelApplication(TypedDict, total=False):
    id: str
    applicant_id: str
    destination_city: str
    destination_tier: str
    travel_scope: str
    purpose: str
    planned_start: str
    planned_end: str
    estimated_budget: float
    urgent: bool
    status: str
    required_chain: List[str]
    standard_version_pinned: int
    total_booked_cost: float
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ItinerarySegment(TypedDict, total=False):
    id: str
    application_id: str
    segment_type: str
    option_code: str
    start_at: str
    end_at: str
    cost: float
    status: str
    prior_segment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    applicant_id: str
    invoice_number: str
    invoice_code: str
    amount: float
    invoice_date: str
    category: str
    ocr_status: str
    matched_segment_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementForm(TypedDict, total=False):
    id: str
    application_id: str
    applicant_id: str
    status: str
    total_claimed: float
    total_reimbursable: float
    total_self_paid: float
    requires_special_approval: bool
    special_approval_granted: bool
    correction_round: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementItem(TypedDict, total=False):
    id: str
    form_id: str
    invoice_id: str
    category: str
    covered_days: int
    claimed_amount: float
    reimbursable_amount: float
    self_paid_amount: float
    standard_cap_applied: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once history row (PRD §2.4)
class ApprovalRecord(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_id: str
    actor_role: str
    action: str
    comment: Optional[str]
    from_status: str
    to_status: str
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    form_id: str
    channel: str
    amount: float
    batch_id: str
    status: str
    attempt_count: int
    external_ref: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once history row (PRD §2.4)
class AuditLog(TypedDict, total=False):
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "EmployeeStatus", "EmployeeLevel",
    "CityTier", "TravelScope",
    "TravelApplicationStatus", "SegmentType", "SegmentStatus",
    "InvoiceCategory", "InvoiceOcrStatus",
    "ReimbursementFormStatus",
    "PaymentStatus", "PaymentChannel", "PaymentOutcome",
    "TaxVerifyVerdict",
    "ApprovalAction", "ApprovalActorRole", "ApprovalSubjectType",
    "AuditEventType", "AuditSubjectType",
    "CHAIN_STEP_SUPERVISOR", "CHAIN_STEP_DEPT_HEAD",
    "CHAIN_STEP_FINANCE", "CHAIN_STEP_GM",
    "Employee", "ExpenseStandard", "TravelApplication",
    "ItinerarySegment", "Invoice",
    "ReimbursementForm", "ReimbursementItem",
    "ApprovalRecord", "Payment", "AuditLog",
]
