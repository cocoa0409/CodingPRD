"""Domain types: entity TypedDicts, status enums, and the role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Trial, Arm, Participant, Visit, AdverseEvent, IRBReview each carry id,
  created_at, updated_at, and version. PRD §2.4: "Top-level operational
  resources — Trial, Arm, Participant, Visit, AdverseEvent, and IRBReview
  — carry a standard set of system-managed fields: id …, created_at …,
  updated_at …, and version …."

- ConsentVersion and Payment are append-only. PRD §2.4: "Two entities
  are immutable-after-write and carry only id and created_at — they
  have no updated_at and no version field. These are ConsentVersion
  (a published consent record is an audit row, not a mutable entity)
  and Payment (each ledger line is a permanent row; corrections are
  issued as additional REVERSAL rows rather than in-place edits)."
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    IRB_REVIEWER = "IRBReviewer"
    STUDY_COORDINATOR = "StudyCoordinator"
    PARTICIPANT_SELF = "Participant_self"


# ---------------------------------------------------------------------------
# Trial — PRD §3.1 / §3.3.
# ---------------------------------------------------------------------------
class TrialStatus(str, Enum):
    DRAFT = "DRAFT"
    IRB_PENDING = "IRB_PENDING"
    APPROVED = "APPROVED"
    OPEN_FOR_ENROLLMENT = "OPEN_FOR_ENROLLMENT"
    CLOSED_TO_ENROLLMENT = "CLOSED_TO_ENROLLMENT"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class RandomizationScheme(str, Enum):
    SIMPLE_BERNOULLI = "SIMPLE_BERNOULLI"
    PERMUTED_BLOCK = "PERMUTED_BLOCK"
    STRATIFIED_BLOCK = "STRATIFIED_BLOCK"


# ---------------------------------------------------------------------------
# Participant — PRD §3.4 / §3.5.
# ---------------------------------------------------------------------------
class ParticipantStatus(str, Enum):
    SCREENING = "SCREENING"
    ELIGIBLE = "ELIGIBLE"
    CONSENT_PENDING = "CONSENT_PENDING"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    INELIGIBLE = "INELIGIBLE"


# ---------------------------------------------------------------------------
# Visit — PRD §3.6.
# ---------------------------------------------------------------------------
class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# AdverseEvent — PRD §3.7.
# ---------------------------------------------------------------------------
class AdverseEventSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    LIFE_THREATENING = "LIFE_THREATENING"


class AdverseEventStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED_HOLD = "ESCALATED_HOLD"


# ---------------------------------------------------------------------------
# IRBReview — PRD §3.2.
# ---------------------------------------------------------------------------
class IRBDecision(str, Enum):
    APPROVED = "APPROVED"
    REVISIONS_REQUESTED = "REVISIONS_REQUESTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Payment — PRD §3.8.
# ---------------------------------------------------------------------------
class PaymentKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REVERSAL = "REVERSAL"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version — PRD §2.4.
# ---------------------------------------------------------------------------
class Trial(TypedDict, total=False):
    id: str
    protocol_code: str
    title: str
    sponsor_org: str
    status: str
    inclusion_criteria: List[Dict[str, Any]]
    exclusion_criteria: List[Dict[str, Any]]
    active_consent_version: Optional[int]
    randomization_scheme: str
    block_size: Optional[int]
    stratification_field: Optional[str]
    target_enrollment: int
    enrolled_count: int
    irb_decision_note: Optional[str]
    irb_approval_expires_at: Optional[str]
    blood_draw_window_days: int
    created_at: str
    updated_at: str
    version: int


class Arm(TypedDict, total=False):
    id: str
    trial_id: str
    code: str
    label: str
    weight: int
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    trial_id: str
    arm_id: Optional[str]
    profile: Dict[str, Any]
    status: str
    signed_consent_version: Optional[int]
    eligibility_score: Optional[float]
    open_ae_count: int
    enrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    participant_id: str
    sequence_no: int
    target_date: str
    status: str
    actual_draw_at: Optional[str]
    compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict, total=False):
    id: str
    participant_id: str
    severity: str
    status: str
    reported_at: str
    narrative: str
    caused_visit_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IRBReview(TypedDict, total=False):
    id: str
    trial_id: str
    decision: str
    reviewer_id: str
    decided_at: str
    notes: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class ConsentVersion(TypedDict, total=False):
    id: str
    trial_id: str
    version: int
    document_uri: str
    change_summary: Optional[str]
    requires_re_consent: bool
    published_at: str
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    participant_id: str
    visit_id: str
    kind: str
    amount_cents: int
    paid_at: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "TrialStatus",
    "RandomizationScheme",
    "ParticipantStatus",
    "VisitStatus",
    "AdverseEventSeverity",
    "AdverseEventStatus",
    "IRBDecision",
    "PaymentKind",
    "Trial",
    "Arm",
    "Participant",
    "Visit",
    "AdverseEvent",
    "IRBReview",
    "ConsentVersion",
    "Payment",
]
