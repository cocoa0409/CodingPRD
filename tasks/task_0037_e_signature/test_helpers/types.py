"""Domain types for the E-Signature API.

Status enums and entity TypedDicts derived from PRD §2.4 (resource identity)
and PRD §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:

- Standard resources (Template, TemplateVersion, Contract, SigningStep,
  SigningParty, EvidencePackage, ReminderRule, OrgUser) carry id, created_at,
  updated_at, version.

- Append-only entries (IdentityVerification, TimestampToken, ReminderEvent,
  AuditLog) carry only id and created_at -- tests MUST NOT assert
  updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TEMPLATE_ADMIN = "TemplateAdmin"
    CONTRACT_INITIATOR = "ContractInitiator"
    SIGNER = "Signer"
    EVIDENCE_ARCHIVIST = "EvidenceArchivist"
    PLATFORM_ADMIN = "PlatformAdmin"
    SYSTEM_SWEEPER = "SystemSweeper"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class TemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TemplateVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGN = "PENDING_SIGN"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    MANUAL = "MANUAL"
    EXPIRED_AUTO = "EXPIRED_AUTO"
    REJECTED_BY_PARTY = "REJECTED_BY_PARTY"


class SigningStepStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SIGNED = "SIGNED"
    SKIPPED = "SKIPPED"
    REJECTED = "REJECTED"


class SigningStepMode(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL_COUNTERSIGN = "PARALLEL_COUNTERSIGN"


class SigningPartyStatus(str, Enum):
    WAITING = "WAITING"
    AUTHENTICATING = "AUTHENTICATING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    SKIPPED = "SKIPPED"


class SignerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORG_LEGAL_REP = "ORG_LEGAL_REP"
    ORG_DELEGATE = "ORG_DELEGATE"


class AuthFactor(str, Enum):
    SMS = "SMS"
    FACE = "FACE"
    CA_CERT = "CA_CERT"
    BANK_CARD = "BANK_CARD"


class FactorOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class IdentityVerificationResult(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class IdentityStrength(str, Enum):
    WEAK = "WEAK"
    STRONG = "STRONG"
    EXTRA_STRONG = "EXTRA_STRONG"


class EvidencePackageStatus(str, Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    SEALED = "SEALED"
    EXPORTED = "EXPORTED"


class NotaryProvider(str, Enum):
    NONE = "NONE"
    NOTARY_PUBLIC = "NOTARY_PUBLIC"
    BLOCKCHAIN = "BLOCKCHAIN"


class EvidenceTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    NOTARIZED = "NOTARIZED"


class TimestampVerificationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class TemplateCategory(str, Enum):
    HR = "HR"
    SALES = "SALES"
    PROCUREMENT = "PROCUREMENT"
    LEGAL = "LEGAL"
    FINANCE = "FINANCE"
    OTHER = "OTHER"


class PermissionScope(str, Enum):
    ORG_ONLY = "ORG_ONLY"
    CROSS_ORG = "CROSS_ORG"
    PUBLIC = "PUBLIC"


class OrgRole(str, Enum):
    LEGAL_REP = "LEGAL_REP"
    AUTHORIZED_DELEGATE = "AUTHORIZED_DELEGATE"
    EMPLOYEE = "EMPLOYEE"


class OrgUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReminderChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"
    IM = "IM"
    INITIATOR_IM = "INITIATOR_IM"  # added on escalation only


class AuditAction(str, Enum):
    TEMPLATE_PUBLISHED = "TEMPLATE_PUBLISHED"
    TEMPLATE_DEPRECATED = "TEMPLATE_DEPRECATED"
    CONTRACT_INITIATED = "CONTRACT_INITIATED"
    CONTRACT_ACTIVATED = "CONTRACT_ACTIVATED"
    PARTY_SIGNED = "PARTY_SIGNED"
    PARTY_REJECTED = "PARTY_REJECTED"
    CONTRACT_VOIDED = "CONTRACT_VOIDED"
    CONTRACT_EXPIRED_AUTO = "CONTRACT_EXPIRED_AUTO"
    CONTRACT_REINITIATED = "CONTRACT_REINITIATED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    EVIDENCE_EXPORTED = "EVIDENCE_EXPORTED"
    REMINDER_FIRED = "REMINDER_FIRED"


# ---------------------------------------------------------------------------
# Standard resources (PRD §2.4 -- carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Template(TypedDict, total=False):
    id: str
    name: str
    category: str
    owner_org_id: str
    permission_scope: str
    latest_version_number: int
    published_version_number: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemplateVersion(TypedDict, total=False):
    id: str
    template_id: str
    version_number: int
    document_blob_sha256: str
    page_count: int
    variable_fields: List[Dict[str, Any]]
    signature_positions: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    template_version_id: str
    initiator_user_id: str
    initiator_org_id: str
    title: str
    variable_values: Dict[str, Any]
    status: str
    expires_at: str
    activated_at: Optional[str]
    completed_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    reinitiated_from_contract_id: Optional[str]
    document_fingerprint_sha256: Optional[str]
    signing_progress_percent: float
    evidence_strength_score: float
    evidence_tier: str
    created_at: str
    updated_at: str
    version: int


class SigningStep(TypedDict, total=False):
    id: str
    contract_id: str
    step_index: int
    mode: str
    branch_condition: Optional[Dict[str, Any]]
    status: str
    activated_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SigningParty(TypedDict, total=False):
    id: str
    signing_step_id: str
    contract_id: str
    role_key: str
    signer_type: str
    signer_user_id: str
    signer_org_id: Optional[str]
    delegation_authorization_id: Optional[str]
    required_auth_factors: List[str]
    status: str
    signed_at: Optional[str]
    timestamp_token_id: Optional[str]
    identity_verification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidencePackage(TypedDict, total=False):
    id: str
    contract_id: str
    status: str
    package_sha256: Optional[str]
    notary_provider: str
    notary_reference: Optional[str]
    sealed_at: Optional[str]
    exported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReminderRule(TypedDict, total=False):
    id: str
    contract_id: str
    interval_hours: int
    channels: List[str]
    escalation_after_misses: int
    enabled: bool
    last_fired_at: Optional[str]
    misses_count: int
    created_at: str
    updated_at: str
    version: int


class OrgUser(TypedDict, total=False):
    id: str
    legal_name: str
    org_id: str
    org_role: str
    registered_factors: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only resources (PRD §2.4 -- only id and created_at)
# ---------------------------------------------------------------------------
class IdentityVerification(TypedDict, total=False):
    id: str
    subject_user_id: str
    contract_id: Optional[str]
    signing_party_id: Optional[str]
    factors_attempted: List[Dict[str, Any]]
    factors_passed: List[str]
    real_name_match: bool
    org_binding_verified: bool
    identity_strength: str
    result: str
    archived_at: str
    created_at: str


class TimestampToken(TypedDict, total=False):
    id: str
    contract_id: str
    signing_party_id: str
    server_anchor_at: str
    tsa_anchor_at: str
    tsa_provider: str
    tsa_token_value: str
    hash_signed: str
    drift_seconds: float
    verification_status: str
    created_at: str


class ReminderEvent(TypedDict, total=False):
    id: str
    reminder_rule_id: str
    contract_id: str
    fired_at: str
    channels_used: List[str]
    escalated: bool
    idempotency_key: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    contract_id: Optional[str]
    template_id: Optional[str]
    actor_user_id: str
    actor_role: str
    action: str
    payload_sha256: str
    prev_log_sha256: Optional[str]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "TemplateStatus",
    "TemplateVersionStatus",
    "ContractStatus",
    "VoidReason",
    "SigningStepStatus",
    "SigningStepMode",
    "SigningPartyStatus",
    "SignerType",
    "AuthFactor",
    "FactorOutcome",
    "IdentityVerificationResult",
    "IdentityStrength",
    "EvidencePackageStatus",
    "NotaryProvider",
    "EvidenceTier",
    "TimestampVerificationStatus",
    "TemplateCategory",
    "PermissionScope",
    "OrgRole",
    "OrgUserStatus",
    "ReminderChannel",
    "AuditAction",
    "Template",
    "TemplateVersion",
    "Contract",
    "SigningStep",
    "SigningParty",
    "EvidencePackage",
    "ReminderRule",
    "OrgUser",
    "IdentityVerification",
    "TimestampToken",
    "ReminderEvent",
    "AuditLog",
]
