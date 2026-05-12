"""Domain types for the Enterprise Procurement API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties) and the entity / state-machine prose in §3. Append-only
auxiliary entities per PRD §2.4 — ApprovalStep, ContractVersion,
PaymentSchedule, AuditLogEntry — expose only `id` and `created_at`; all
other entities carry the full common-fields quartet (`id`, `created_at`,
`updated_at`, `version`).
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any, Dict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REQUESTER = "Requester"
    BUYER = "Buyer"
    DEPARTMENT_HEAD = "DepartmentHead"
    FINANCE_APPROVER = "FinanceApprover"
    LEGAL_APPROVER = "LegalApprover"
    GENERAL_MANAGER = "GeneralManager"
    INSPECTOR = "Inspector"
    SUPPLIER = "Supplier"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity status enums (PRD §3 prose; one per entity with a state machine)
# ---------------------------------------------------------------------------
class BudgetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class SupplierQualificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    QUALIFIED = "QUALIFIED"
    BLACKLISTED = "BLACKLISTED"


class RequirementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_SOURCING = "IN_SOURCING"
    AWARDED = "AWARDED"
    IN_APPROVAL = "IN_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RequirementCategory(str, Enum):
    IT_HARDWARE = "IT_HARDWARE"
    IT_SOFTWARE = "IT_SOFTWARE"
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES"
    PROFESSIONAL_SERVICES = "PROFESSIONAL_SERVICES"
    MARKETING = "MARKETING"
    CAPEX_EQUIPMENT = "CAPEX_EQUIPMENT"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PurchaseOrderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CONTRACTED = "CONTRACTED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"


class PurchaseOrderTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class ApprovalStepStage(str, Enum):
    DEPARTMENT_HEAD = "DEPARTMENT_HEAD"
    FINANCE = "FINANCE"
    LEGAL = "LEGAL"
    GENERAL_MANAGER = "GENERAL_MANAGER"


class ApprovalStepMode(str, Enum):
    SERIAL = "SERIAL"
    PARALLEL = "PARALLEL"


class ApprovalStepStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    SKIPPED = "SKIPPED"


class ContractStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class PaymentTermsType(str, Enum):
    ADVANCE = "ADVANCE"
    ON_DELIVERY = "ON_DELIVERY"
    NET_N_DAYS = "NET_N_DAYS"
    INSTALLMENT = "INSTALLMENT"


class ClauseTemplateCategory(str, Enum):
    PAYMENT = "PAYMENT"
    DELIVERY = "DELIVERY"
    WARRANTY = "WARRANTY"
    IP = "IP"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    TERMINATION = "TERMINATION"


class ReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    INSPECTING = "INSPECTING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class PaymentScheduleStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class AuditLogAction(str, Enum):
    APPROVAL_STEP_APPROVE = "APPROVAL_STEP_APPROVE"
    APPROVAL_STEP_REJECT = "APPROVAL_STEP_REJECT"
    APPROVAL_STEP_DELEGATE = "APPROVAL_STEP_DELEGATE"
    APPROVAL_STEP_ESCALATE = "APPROVAL_STEP_ESCALATE"
    CONTRACT_VERSION_CREATED = "CONTRACT_VERSION_CREATED"
    CONTRACT_SIGNED = "CONTRACT_SIGNED"
    CONTRACT_AMENDED = "CONTRACT_AMENDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# PRD §2.4 — append-only auxiliary entities (ApprovalStep, ContractVersion,
# PaymentSchedule, AuditLogEntry) carry only id + created_at; everything
# else carries the full common-fields quartet.
# ---------------------------------------------------------------------------
class BudgetAccount(TypedDict, total=False):
    id: str
    code: str
    department: str
    fiscal_year: int
    total_amount_cents: int
    committed_amount_cents: int
    spent_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    qualification_status: str
    qualification_categories: List[str]
    qualification_expires_at: str
    bank_account_id: str
    rating_avg: float
    created_at: str
    updated_at: str
    version: int


class Requirement(TypedDict, total=False):
    id: str
    requester_id: str
    category: str
    specification: str
    quantity: int
    unit: str
    expected_delivery_date: str
    budget_account_id: str
    estimated_unit_price_cents: int
    estimated_total_cents: int
    attachment_uri: Optional[str]
    status: str
    justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    requirement_id: str
    supplier_id: str
    unit_price_cents: int
    lead_time_days: int
    technical_score: float
    commercial_score: float
    composite_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    requirement_id: str
    awarded_quote_id: str
    supplier_id: str
    budget_account_id: str
    total_amount_cents: int
    tier: str
    status: str
    approval_started_at: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4 — only id + created_at.
class ApprovalStep(TypedDict, total=False):
    id: str
    purchase_order_id: str
    stage: str
    mode: str
    assignee_role: str
    assignee_user_id: str
    original_assignee_user_id: str
    status: str
    deadline_at: str
    decided_at: Optional[str]
    decision_comment: Optional[str]
    created_at: str


class Contract(TypedDict, total=False):
    id: str
    purchase_order_id: str
    clause_template_ids: List[str]
    payment_terms_type: str
    payment_terms_params: Dict[str, Any]
    parties_required: List[str]
    signatures: List[Dict[str, Any]]
    current_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4 — only id + created_at.
class ContractVersion(TypedDict, total=False):
    id: str
    contract_id: str
    version_number: int
    clause_template_ids_snapshot: List[str]
    payment_terms_snapshot: Dict[str, Any]
    change_reason: str
    created_at: str


class ClauseTemplate(TypedDict, total=False):
    id: str
    code: str
    title: str
    body: str
    category: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict, total=False):
    id: str
    purchase_order_id: str
    delivery_note_no: str
    received_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    quality_rating: float
    status: str
    cumulative_accepted_after: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4 — only id + created_at.
class PaymentSchedule(TypedDict, total=False):
    id: str
    purchase_order_id: str
    contract_id: str
    installment_no: int
    due_date: str
    amount_cents: int
    status: str
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    payment_schedule_id: str
    invoice_id: str
    amount_cents: int
    status: str
    bank_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    purchase_order_id: str
    supplier_id: str
    invoice_no: str
    invoice_date: str
    invoiced_quantity: int
    invoiced_amount_cents: int
    tax_amount_cents: int
    tax_rate_declared: float
    status: str
    matching_result: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4 — only id + created_at.
class AuditLogEntry(TypedDict, total=False):
    id: str
    actor_user_id: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "BudgetAccountStatus",
    "SupplierQualificationStatus",
    "RequirementStatus",
    "RequirementCategory",
    "QuoteStatus",
    "PurchaseOrderStatus",
    "PurchaseOrderTier",
    "ApprovalStepStage",
    "ApprovalStepMode",
    "ApprovalStepStatus",
    "ContractStatus",
    "PaymentTermsType",
    "ClauseTemplateCategory",
    "ReceiptStatus",
    "PaymentScheduleStatus",
    "PaymentStatus",
    "InvoiceStatus",
    "AuditLogAction",
    "BudgetAccount",
    "Supplier",
    "Requirement",
    "Quote",
    "PurchaseOrder",
    "ApprovalStep",
    "Contract",
    "ContractVersion",
    "ClauseTemplate",
    "Receipt",
    "PaymentSchedule",
    "Payment",
    "Invoice",
    "AuditLogEntry",
]
