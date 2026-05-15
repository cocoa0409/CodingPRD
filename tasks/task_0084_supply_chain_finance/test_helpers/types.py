"""Domain types for the Supply Chain Finance API.

Entity TypedDicts, status enums, and role enum derived from PRD §2.4
(common resource properties) and PRD §3 (per-entity lifecycles).

PRD §2.4: most entities carry id + created_at + updated_at + version;
``Disbursement``, ``TradeBackgroundVerification``, and ``AuditLogEntry``
carry only id + created_at (no updated_at, no version).
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# User roles (PRD §2.1) — nine recognised role names.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CORE_ENTERPRISE_USER = "CoreEnterpriseUser"
    SUPPLIER_USER = "SupplierUser"
    CREDIT_OFFICER = "CreditOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RISK_REVIEWER = "RiskReviewer"
    CREDIT_APPROVER = "CreditApprover"
    FUNDER = "Funder"
    COLLECTION_MANAGER = "CollectionManager"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# CoreEnterprise (PRD §3.1)
# ---------------------------------------------------------------------------
class CoreEnterpriseOnboardingStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class CoreEnterpriseRiskRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"


# ---------------------------------------------------------------------------
# Supplier (PRD §3.2)
# ---------------------------------------------------------------------------
class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLACKLISTED = "BLACKLISTED"


class SupplierKycStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# PayableConfirmation (PRD §3.3)
# ---------------------------------------------------------------------------
class PayableConfirmationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Receivable (PRD §3.4)
# ---------------------------------------------------------------------------
class ReceivableStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PLEDGED = "PLEDGED"
    TRANSFERRED = "TRANSFERRED"
    FINANCED = "FINANCED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# FinancingApplication (PRD §3.5)
# ---------------------------------------------------------------------------
class FinancingApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class FinancingMode(str, Enum):
    FACTORING = "FACTORING"
    REVERSE_FACTORING = "REVERSE_FACTORING"
    DYNAMIC_DISCOUNTING = "DYNAMIC_DISCOUNTING"
    RECEIVABLE_PLEDGE = "RECEIVABLE_PLEDGE"


class FinancingRiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# RepaymentSchedule (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
class RepaymentScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SETTLED = "SETTLED"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# CollectionCase (PRD §3.8)
# ---------------------------------------------------------------------------
class CollectionStage(str, Enum):
    SOFT = "SOFT"
    HARD = "HARD"
    JOINT_LIABILITY = "JOINT_LIABILITY"
    LEGAL = "LEGAL"
    WRITTEN_OFF = "WRITTEN_OFF"
    CLOSED = "CLOSED"


class AgingBucket(str, Enum):
    DPD_1_30 = "DPD_1_30"
    DPD_31_60 = "DPD_31_60"
    DPD_61_90 = "DPD_61_90"
    DPD_OVER_90 = "DPD_OVER_90"


# ---------------------------------------------------------------------------
# TradeBackgroundVerification (PRD §3.9)
# ---------------------------------------------------------------------------
class VerificationOutcome(str, Enum):
    INCONCLUSIVE = "INCONCLUSIVE"
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# AuditLogEntry action enum (PRD §3.10)
# ---------------------------------------------------------------------------
class AuditAction(str, Enum):
    CONFIRM = "CONFIRM"
    REVOKE = "REVOKE"
    REGISTER = "REGISTER"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DISBURSE = "DISBURSE"
    REPAY = "REPAY"
    WRITE_OFF = "WRITE_OFF"
    CENTRAL_REGISTRY_FILE = "CENTRAL_REGISTRY_FILE"
    ERP_SYNC = "ERP_SYNC"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# CoreEnterprise — PRD §2.4 says "Most entities ... additionally expose
# created_at, updated_at, and a monotonically increasing integer version."
class CoreEnterprise(TypedDict, total=False):
    id: str
    legal_name: str
    unified_credit_code: str
    onboarding_status: str
    credit_line_total_cents: int
    credit_line_reserved_cents: int
    credit_line_consumed_cents: int
    erp_endpoint_url: str
    joint_liability_flag: bool
    risk_rating: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    legal_name: str
    unified_credit_code: str
    tier_to_core: int
    parent_supplier_id: Optional[str]
    kyc_status: str
    kyc_completed_at: Optional[str]
    aml_risk_score: float
    bank_account_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayableConfirmation(TypedDict, total=False):
    id: str
    core_enterprise_id: str
    supplier_id: str
    invoice_number: str
    contract_number: str
    amount_cents: int
    due_date: str
    tier: int
    status: str
    confirmed_at: Optional[str]
    revoke_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receivable(TypedDict, total=False):
    id: str
    confirmation_id: str
    supplier_id: str
    core_enterprise_id: str
    amount_cents: int
    due_date: str
    invoice_doc_id: str
    contract_doc_id: str
    status: str
    central_registry_required: bool
    central_registry_filing_no: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict, total=False):
    id: str
    receivable_id: str
    supplier_id: str
    mode: str
    requested_amount_cents: int
    term_days: int
    supporting_doc_ids: List[str]
    pinned_core_enterprise_version: Optional[int]
    pinned_receivable_version: Optional[int]
    status: str
    risk_rating: Optional[str]
    approved_amount_cents: Optional[int]
    approved_apr_bps: Optional[int]
    revision_round: int
    created_at: str
    updated_at: str
    version: int


# Disbursement — PRD §2.4: "Disbursement and TradeBackgroundVerification
# carry only id and created_at (no updated_at, no version)."
class Disbursement(TypedDict, total=False):
    id: str
    application_id: str
    funder_account_id: str
    principal_cents: int
    discount_cents: int
    net_to_supplier_cents: int
    fees_cents: int
    released_at: str
    reconciled_at: Optional[str]
    created_at: str


class RepaymentSchedule(TypedDict, total=False):
    id: str
    application_id: str
    scheduled_repayment_date: str
    total_due_cents: int
    paid_cents: int
    status: str
    prepayment_count: int
    created_at: str
    updated_at: str
    version: int


class CollectionCase(TypedDict, total=False):
    id: str
    schedule_id: str
    aging_bucket: Optional[str]
    stage: str
    reminder_count: int
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


# TradeBackgroundVerification — PRD §2.4 lean entity (id + created_at only).
class TradeBackgroundVerification(TypedDict, total=False):
    id: str
    receivable_id: str
    waybill_doc_id: Optional[str]
    customs_declaration_doc_id: Optional[str]
    capital_flow_match: bool
    third_party_score: float
    on_site_required: bool
    on_site_completed: bool
    outcome: str
    created_at: str


# AuditLogEntry — PRD §2.4: "the append-only AuditLogEntry similarly carries
# id and created_at only, with no mutation semantics."
class AuditLogEntry(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    actor_id: str
    amount_cents: Optional[int]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "CoreEnterpriseOnboardingStatus",
    "CoreEnterpriseRiskRating",
    "SupplierStatus",
    "SupplierKycStatus",
    "PayableConfirmationStatus",
    "ReceivableStatus",
    "FinancingApplicationStatus",
    "FinancingMode",
    "FinancingRiskRating",
    "RepaymentScheduleStatus",
    "CollectionStage",
    "AgingBucket",
    "VerificationOutcome",
    "AuditAction",
    "CoreEnterprise",
    "Supplier",
    "PayableConfirmation",
    "Receivable",
    "FinancingApplication",
    "Disbursement",
    "RepaymentSchedule",
    "CollectionCase",
    "TradeBackgroundVerification",
    "AuditLogEntry",
]
