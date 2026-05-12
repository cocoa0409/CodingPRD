"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Customer, Evidence, OnChainTx, Batch, Certificate, JudicialPackage, Invoice.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version):
  FeeAccount, TimestampNotarization, VerificationReport, Recharge, AuditLog.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    NOTARY_OFFICER = "NotaryOfficer"
    JUDICIAL_OFFICER = "JudicialOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class OnChainTxStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class JudicialPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class RechargeStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Other enums
# ---------------------------------------------------------------------------
class EvidenceType(str, Enum):
    DOCUMENT = "DOCUMENT"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CODE_REPOSITORY = "CODE_REPOSITORY"
    DATASET = "DATASET"


class ChainId(str, Enum):
    ETHEREUM = "ETHEREUM"
    FABRIC = "FABRIC"
    BSN = "BSN"
    COSMOS = "COSMOS"


class HashAlgorithm(str, Enum):
    SHA256 = "SHA256"
    SM3 = "SM3"


class CertificateTemplate(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    JUDICIAL = "JUDICIAL"


class TsaProvider(str, Enum):
    RFC3161_TSA_A = "RFC3161_TSA_A"
    RFC3161_TSA_B = "RFC3161_TSA_B"
    NOTARY_OFFICE = "NOTARY_OFFICE"


class AuthorityCode(str, Enum):
    COURT_BJ = "COURT_BJ"
    COURT_SH = "COURT_SH"
    COURT_GZ = "COURT_GZ"
    COURT_SZ = "COURT_SZ"
    PROCURATORATE = "PROCURATORATE"
    ARBITRATION = "ARBITRATION"


class InvoiceScope(str, Enum):
    SINGLE_EVIDENCE = "SINGLE_EVIDENCE"
    SINGLE_BATCH = "SINGLE_BATCH"
    BILLING_PERIOD = "BILLING_PERIOD"


class VerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    TAMPERED = "TAMPERED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    UNAVAILABLE = "UNAVAILABLE"


class AuditEventType(str, Enum):
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    EVIDENCE_CONFIRMED = "EVIDENCE_CONFIRMED"
    EVIDENCE_FAILED = "EVIDENCE_FAILED"
    EVIDENCE_RESUBMITTED = "EVIDENCE_RESUBMITTED"
    BATCH_CONFIRMED = "BATCH_CONFIRMED"
    CERTIFICATE_ISSUED = "CERTIFICATE_ISSUED"
    JUDICIAL_SEALED = "JUDICIAL_SEALED"
    JUDICIAL_DELIVERED = "JUDICIAL_DELIVERED"
    FEE_DEBITED = "FEE_DEBITED"
    RECHARGE_COMPLETED = "RECHARGE_COMPLETED"
    INVOICE_ISSUED = "INVOICE_ISSUED"


# ---------------------------------------------------------------------------
# Versioned entity TypedDicts (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    display_name: str
    wallet_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Evidence(TypedDict):
    id: str
    customer_id: str
    evidence_type: str
    storage_period_days: int
    hash_algorithm: str
    file_hash: str
    original_data_b64: Optional[str]
    chain_id: str
    status: str
    submission_attempts: int
    per_evidence_fee_cents: Optional[int]
    batch_id: Optional[str]
    confirmed_at: Optional[str]
    expires_at: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OnChainTx(TypedDict):
    id: str
    evidence_id: Optional[str]
    batch_id: Optional[str]
    chain_id: str
    anchored_hash: str
    tx_hash: Optional[str]
    block_height: Optional[int]
    confirmations: int
    status: str
    attempt_index: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    customer_id: str
    chain_id: str
    evidence_count: int
    merkle_root: str
    status: str
    total_fee_cents: Optional[int]
    submission_attempts: int
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    evidence_id: str
    template_code: str
    verification_code: str
    embedded_timestamp: str
    tx_hash_ref: str
    chain_id: str
    hash_snapshot: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JudicialPackage(TypedDict):
    id: str
    evidence_id: str
    case_number: str
    party_info: Dict[str, Any]
    authority_code: str
    include_original_data: bool
    status: str
    official_seal_id: Optional[str]
    delivered_at: Optional[str]
    surcharge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    customer_id: str
    scope: str
    scope_ref_id: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (id + created_at ONLY; PRD §2.4)
# ---------------------------------------------------------------------------
class FeeAccount(TypedDict):
    id: str
    customer_id: str
    lifetime_recharge_cents: int
    lifetime_deduction_cents: int
    created_at: str


class TimestampNotarization(TypedDict):
    id: str
    evidence_id: str
    tsa_provider: str
    notary_office_id: Optional[str]
    trusted_time: Optional[str]
    tsa_token: Optional[str]
    created_at: str


class VerificationReport(TypedDict):
    id: str
    evidence_id: str
    recomputed_hash: str
    on_chain_hash: str
    certificate_valid: bool
    tamper_detected: bool
    outcome: str
    created_at: str


class Recharge(TypedDict):
    id: str
    customer_id: str
    amount_cents: int
    external_payment_ref: str
    status: str
    created_at: str


class AuditLog(TypedDict):
    id: str
    actor_role: str
    actor_id: Optional[str]
    event_type: str
    target_entity: str
    target_id: str
    detail: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "CustomerStatus", "EvidenceStatus", "OnChainTxStatus", "BatchStatus",
    "CertificateStatus", "JudicialPackageStatus", "RechargeStatus", "InvoiceStatus",
    "EvidenceType", "ChainId", "HashAlgorithm", "CertificateTemplate",
    "TsaProvider", "AuthorityCode", "InvoiceScope", "VerificationOutcome",
    "AuditEventType",
    "Customer", "Evidence", "OnChainTx", "Batch", "Certificate",
    "JudicialPackage", "Invoice",
    "FeeAccount", "TimestampNotarization", "VerificationReport",
    "Recharge", "AuditLog",
]
