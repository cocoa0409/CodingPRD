"""Domain types for the Legal Case Management API.

Status enums, role enum, and entity TypedDicts. Field names are PRD-exact.

PRD §2.4 distinguishes entities that carry common audit fields
(``id``, ``created_at``, ``updated_at``, ``version``) from append-only logs
that carry only ``id`` and ``created_at`` — namely CustodyEvent,
EvidenceRebuttal, and AuditLog. Their TypedDicts intentionally omit
``updated_at`` and ``version``.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PARTNER = "PartnerLawyer"
    SENIOR = "SeniorLawyer"
    JUNIOR = "JuniorLawyer"
    INTAKE = "IntakeClerk"
    SYSTEM = "SystemIntegrator"


# ---------------------------------------------------------------------------
# Status enums (one per state machine)
# ---------------------------------------------------------------------------
class LawyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LawyerRank(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    PARTNER = "PARTNER"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    AWAITING_SETTLEMENT = "AWAITING_SETTLEMENT"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class CaseType(str, Enum):
    CIVIL = "CIVIL"
    CRIMINAL = "CRIMINAL"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    ARBITRATION = "ARBITRATION"


class CasePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PartyRole(str, Enum):
    PLAINTIFF = "PLAINTIFF"
    DEFENDANT = "DEFENDANT"
    THIRD_PARTY = "THIRD_PARTY"
    WITNESS = "WITNESS"


class PartyAccessLevel(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    NONE = "NONE"


class TemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DocumentDraftStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    REVISING = "REVISING"
    SIGNED_OFF = "SIGNED_OFF"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvidenceType(str, Enum):
    DOCUMENTARY = "DOCUMENTARY"
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"
    TESTIMONIAL = "TESTIMONIAL"


class EvidenceStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SUBMITTED = "SUBMITTED"
    REBUTTED = "REBUTTED"
    EXCLUDED = "EXCLUDED"


class CustodyAction(str, Enum):
    COLLECTED = "COLLECTED"
    TRANSFERRED = "TRANSFERRED"
    EXAMINED = "EXAMINED"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"


class RebuttalStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class TimeEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    ADJUSTED = "ADJUSTED"
    WRITTEN_OFF = "WRITTEN_OFF"
    BILLED = "BILLED"


class BillingMode(str, Enum):
    HOURLY = "HOURLY"
    FIXED = "FIXED"
    CONTINGENT = "CONTINGENT"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AuditSubjectType(str, Enum):
    DOCUMENT_DRAFT = "DOCUMENT_DRAFT"
    EVIDENCE = "EVIDENCE"
    CUSTODY_EVENT = "CUSTODY_EVENT"


class SignatureKind(str, Enum):
    DRAFT_LOCKED = "DRAFT_LOCKED"
    BILL_ISSUED = "BILL_ISSUED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (with common audit fields)
# ---------------------------------------------------------------------------
class Lawyer(TypedDict, total=False):
    id: str
    full_name: str
    bar_number: str
    role: str  # JUNIOR / SENIOR / PARTNER
    hourly_rate_cents: int
    status: str  # ACTIVE / SUSPENDED
    client_history: List[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    case_number: str
    case_type: str
    title: str
    claim_amount_cents: int
    lead_lawyer_id: str
    status: str
    posture: str
    client_identity_hash: str
    opposing_identity_hash: str
    intake_document_id: str
    closed_at: Optional[str]
    settlement_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    case_id: str
    party_role: str
    full_name: str
    id_document_number: str
    identity_verified: bool
    contact_email: str
    contact_phone: str
    agency_lawyer_id: Optional[str]
    access_level: str
    created_at: str
    updated_at: str
    version: int


class DocumentTemplate(TypedDict, total=False):
    id: str
    template_code: str
    case_type: str
    name: str
    variables: List[str]
    body_template: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentDraft(TypedDict, total=False):
    id: str
    case_id: str
    template_id: str
    template_version_pinned: int
    version_number: int
    rendered_body: str
    variable_overrides: Dict[str, Any]
    drafter_lawyer_id: str
    senior_reviewer_lawyer_id: Optional[str]
    partner_signoff_lawyer_id: Optional[str]
    signed_off_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    case_id: str
    court_room: str
    scheduled_start: str
    scheduled_end: str
    lead_lawyer_id: str
    status: str
    prep_tasks_generated: bool
    previous_hearing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evidence(TypedDict, total=False):
    id: str
    case_id: str
    evidence_type: str
    collected_at: str
    collected_by_lawyer_id: str
    case_fact_refs: List[str]
    status: str
    submitted_at: Optional[str]
    rebuttal_count: int
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict, total=False):
    id: str
    case_id: str
    lawyer_id: str
    task_label: str
    minutes: int
    billable: bool
    hourly_rate_cents_pinned: int
    status: str
    adjustment_minutes: int
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    case_id: str
    billing_mode: str
    fixed_fee_cents: Optional[int]
    contingent_rate_bps: Optional[int]
    recovered_amount_cents: int
    court_fee_cents: int
    attorney_fee_cents: int
    expense_reimbursement_cents: int
    cost_recovery_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only logs (PRD §2.4 — only id + created_at; no updated_at / version)
# ---------------------------------------------------------------------------
class CustodyEvent(TypedDict, total=False):
    id: str
    evidence_id: str
    actor_lawyer_id: str
    action: str
    occurred_at: str
    location: str
    created_at: str


class EvidenceRebuttal(TypedDict, total=False):
    id: str
    evidence_id: str
    filed_by_lawyer_id: str
    ground: str
    status: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    action: str
    payload_snapshot: Dict[str, Any]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "LawyerStatus",
    "LawyerRank",
    "CaseStatus",
    "CaseType",
    "CasePosture",
    "PartyRole",
    "PartyAccessLevel",
    "TemplateStatus",
    "DocumentDraftStatus",
    "HearingStatus",
    "EvidenceType",
    "EvidenceStatus",
    "CustodyAction",
    "RebuttalStatus",
    "TimeEntryStatus",
    "BillingMode",
    "BillStatus",
    "AuditSubjectType",
    "SignatureKind",
    "Lawyer",
    "Case",
    "Party",
    "DocumentTemplate",
    "DocumentDraft",
    "Hearing",
    "Evidence",
    "TimeEntry",
    "Bill",
    "CustodyEvent",
    "EvidenceRebuttal",
    "AuditLogEntry",
]
