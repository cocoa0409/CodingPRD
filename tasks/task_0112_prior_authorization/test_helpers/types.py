"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, Provider, ServiceCatalogItem, AuthorizationRequest,
  PeerToPeerReview, and Appeal carry id, created_at, updated_at, and
  version. PRD §2.4: "Almost every primary, top-level resource — Patient,
  Provider, ServiceCatalogItem, AuthorizationRequest, PeerToPeerReview,
  and Appeal — carries a standard set of system-managed fields: id …,
  created_at …, updated_at …, and version …."

- ClinicalEvidence and Decision are append-only audit rows. PRD §2.4:
  "Two entities are deliberate exceptions to this template:
  ClinicalEvidence and Decision. … Both carry id and created_at but omit
  both updated_at and version."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROVIDER = "Provider"
    INITIAL_REVIEWER = "InitialReviewer"
    MEDICAL_DIRECTOR = "MedicalDirector"
    EXTERNAL_REVIEWER = "ExternalReviewer"
    PAYER_REVIEWER = "PayerReviewer"


# ---------------------------------------------------------------------------
# Patient status — PRD §3.1
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PatientPlanType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


# ---------------------------------------------------------------------------
# Provider status — PRD §3.1
# ---------------------------------------------------------------------------
class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# ServiceCatalogItem — PRD §3.1
# ---------------------------------------------------------------------------
class ServiceCatalogItemKind(str, Enum):
    SERVICE = "SERVICE"
    DRUG = "DRUG"


class ServiceCatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EvidenceCategory(str, Enum):
    LAB = "LAB"
    IMAGING = "IMAGING"
    NOTES = "NOTES"
    MED_HISTORY = "MED_HISTORY"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# AuthorizationRequest — PRD §3.2 / §3.4 / §3.9 / §3.10
# ---------------------------------------------------------------------------
class AuthorizationRequestUrgency(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class AuthorizationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_INFO = "PENDING_INFO"
    PEER_REVIEW = "PEER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# ClinicalEvidence — PRD §3.3 (append-only audit row)
# ---------------------------------------------------------------------------
class ClinicalEvidenceStatus(str, Enum):
    ATTACHED = "ATTACHED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# PeerToPeerReview — PRD §3.5
# ---------------------------------------------------------------------------
class PeerToPeerReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PeerToPeerReviewOutcome(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    NO_SHOW = "NO_SHOW"


# ---------------------------------------------------------------------------
# Decision — PRD §3.9 (append-only audit row)
# ---------------------------------------------------------------------------
class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DecisionDeniedByRole(str, Enum):
    INITIAL_REVIEWER = "INITIAL_REVIEWER"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"
    EXTERNAL_REVIEWER = "EXTERNAL_REVIEWER"


class DenialReasonCode(str, Enum):
    NOT_MEDICALLY_NECESSARY = "NOT_MEDICALLY_NECESSARY"
    EXPERIMENTAL = "EXPERIMENTAL"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    NON_COVERED_BENEFIT = "NON_COVERED_BENEFIT"


# ---------------------------------------------------------------------------
# Appeal — PRD §3.11
# ---------------------------------------------------------------------------
class AppealOutcome(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    member_id: str
    full_name: str
    date_of_birth: str
    plan_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    specialty: str
    in_network: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCatalogItem(TypedDict, total=False):
    id: str
    code: str
    kind: str
    name: str
    requires_pa: bool
    standard_sla_hours: int
    expedited_sla_hours: int
    approval_validity_days: int
    required_evidence_categories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    service_code: str
    service_catalog_item_id: str
    service_catalog_item_version: int
    urgency: str
    clinical_justification: str
    requested_units: int
    prior_request_id: Optional[str]
    status: str
    submitted_at: Optional[str]
    decision_deadline_at: Optional[str]
    decided_at: Optional[str]
    expires_at: Optional[str]
    evidence_completeness_score: float
    evidence_reuse_discount: float
    created_at: str
    updated_at: str
    version: int


class PeerToPeerReview(TypedDict, total=False):
    id: str
    authorization_request_id: str
    scheduled_at: str
    duration_minutes: int
    payer_reviewer_id: str
    outcome: str
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    authorization_request_id: str
    tier: int
    reason: str
    filed_at: str
    decision_deadline_at: str
    outcome: str
    decided_at: Optional[str]
    superseded_decision_id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4)
# ---------------------------------------------------------------------------
class ClinicalEvidence(TypedDict, total=False):
    id: str
    authorization_request_id: str
    category: str
    title: str
    uri: str
    byte_size: int
    sourced_from_request_id: Optional[str]
    status: str
    created_at: str


class Decision(TypedDict, total=False):
    id: str
    authorization_request_id: str
    outcome: str
    rationale: str
    approved_units: int
    denial_reason_code: Optional[str]
    decided_by_role: str
    supersedes_decision_id: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "PatientStatus",
    "PatientPlanType",
    "ProviderStatus",
    "ServiceCatalogItemKind",
    "ServiceCatalogItemStatus",
    "EvidenceCategory",
    "AuthorizationRequestUrgency",
    "AuthorizationRequestStatus",
    "ClinicalEvidenceStatus",
    "PeerToPeerReviewStatus",
    "PeerToPeerReviewOutcome",
    "DecisionOutcome",
    "DecisionDeniedByRole",
    "DenialReasonCode",
    "AppealOutcome",
    "Patient",
    "Provider",
    "ServiceCatalogItem",
    "AuthorizationRequest",
    "PeerToPeerReview",
    "Appeal",
    "ClinicalEvidence",
    "Decision",
]
