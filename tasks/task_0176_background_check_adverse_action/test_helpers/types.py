"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — primary resources (Candidate, ConsentDisclosure,
BackgroundCheckOrder, VerificationItem, Dispute, AdverseActionFlow)
carry id + created_at + updated_at + version. PRD §2.4 also notes that
`JurisdictionPolicy` and `AuditEvent` carry only id + created_at —
both `updated_at` and `version` are absent on those rows. The
TypedDicts below mirror that exactly.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    ADJUDICATOR = "Adjudicator"
    VERIFIER = "Verifier"
    CANDIDATE = "Candidate"
    PLATFORM_ADMIN = "PlatformAdmin"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class EligibilityPosture(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADVERSE = "ADVERSE"
    LOCKED = "LOCKED"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_VERIFICATION = "IN_VERIFICATION"
    AWAITING_ADJUDICATION = "AWAITING_ADJUDICATION"
    PRE_ADVERSE_ISSUED = "PRE_ADVERSE_ISSUED"
    AWAITING_FINAL = "AWAITING_FINAL"
    REWORK = "REWORK"
    COMPLETED_CLEAR = "COMPLETED_CLEAR"
    TERMINATED_ADVERSE = "TERMINATED_ADVERSE"
    CANCELLED = "CANCELLED"


class CompositeDecision(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    CONSIDER = "CONSIDER"
    INELIGIBLE = "INELIGIBLE"


class VerificationItemStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    RETURNED = "RETURNED"
    DISPUTED = "DISPUTED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class VerificationItemKind(str, Enum):
    CRIMINAL = "CRIMINAL"
    MVR = "MVR"
    EDUCATION = "EDUCATION"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class AdverseFlowNotificationStatus(str, Enum):
    PENDING_DELIVERY = "PENDING_DELIVERY"
    PRE_DELIVERED = "PRE_DELIVERED"
    FINAL_DELIVERED = "FINAL_DELIVERED"


class AdverseFlowProceduralStatus(str, Enum):
    PRE_AWAITING_DISPUTE_WINDOW = "PRE_AWAITING_DISPUTE_WINDOW"
    DISPUTE_PAUSED = "DISPUTE_PAUSED"
    READY_FOR_FINAL = "READY_FOR_FINAL"
    FINALIZED = "FINALIZED"
    ABANDONED = "ABANDONED"


class BanTheBoxStage(str, Enum):
    PRE_OFFER = "PRE_OFFER"
    POST_INTERVIEW = "POST_INTERVIEW"
    POST_OFFER = "POST_OFFER"


class CriminalSeverity(str, Enum):
    INFRACTION = "INFRACTION"
    MISDEMEANOR = "MISDEMEANOR"
    FELONY = "FELONY"


class LicenseStatus(str, Enum):
    VALID = "VALID"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class AuditEventType(str, Enum):
    CONSENT_RECORDED = "CONSENT_RECORDED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    ORDER_OPENED = "ORDER_OPENED"
    ITEM_RETURNED = "ITEM_RETURNED"
    ITEM_FAILED = "ITEM_FAILED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    PRE_ADVERSE_SENT = "PRE_ADVERSE_SENT"
    FINAL_ADVERSE_ISSUED = "FINAL_ADVERSE_ISSUED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    REWORK_REQUESTED = "REWORK_REQUESTED"


class AuditSubjectEntity(str, Enum):
    CANDIDATE = "Candidate"
    BACKGROUND_CHECK_ORDER = "BackgroundCheckOrder"
    VERIFICATION_ITEM = "VerificationItem"
    DISPUTE = "Dispute"
    ADVERSE_ACTION_FLOW = "AdverseActionFlow"
    CONSENT_DISCLOSURE = "ConsentDisclosure"


# ===========================================================================
# Entity TypedDicts — PRD §2.4
# ===========================================================================

# Common-fields primary resources — id + created_at + updated_at + version.
class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    residence_jurisdiction: str
    date_of_birth: str
    eligibility_posture: str
    salary_history_disclosed: bool
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentDisclosure(TypedDict, total=False):
    id: str
    candidate_id: str
    disclosure_text_hash: str
    consent_signature: str
    consent_timestamp: str
    disclosure_presented_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheckOrder(TypedDict, total=False):
    id: str
    candidate_id: str
    consent_disclosure_id: str
    stage_at_order: str
    requested_packages: List[str]
    status: str
    composite_decision: str
    opened_by_role: str
    opened_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationItem(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    status: str
    raw_finding: dict
    severity_score: int
    rework_count: int
    dispute_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    verification_item_id: str
    candidate_id: str
    reason_text: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseActionFlow(TypedDict, total=False):
    id: str
    order_id: str
    pre_adverse_notice_sent_at: str
    waiting_period_business_days: int
    earliest_final_eligible_at: str
    final_adverse_action_at: Optional[str]
    notification_status: str
    procedural_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / leaf entities — id + created_at ONLY (PRD §2.4).
class JurisdictionPolicy(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    criminal_lookback_years: int
    salary_history_ban: bool
    ban_the_box_stage: str
    adverse_action_waiting_business_days: int
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    subject_entity: str
    subject_id: str
    actor_role: str
    actor_user_id: str
    previous_event_id: Optional[str]
    payload_hash: str
    created_at: str


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "EligibilityPosture",
    "ConsentStatus",
    "OrderStatus",
    "CompositeDecision",
    "VerificationItemStatus",
    "VerificationItemKind",
    "DisputeStatus",
    "AdverseFlowNotificationStatus",
    "AdverseFlowProceduralStatus",
    "BanTheBoxStage",
    "CriminalSeverity",
    "LicenseStatus",
    "AuditEventType",
    "AuditSubjectEntity",
    # Entity TypedDicts
    "Candidate",
    "ConsentDisclosure",
    "BackgroundCheckOrder",
    "VerificationItem",
    "Dispute",
    "AdverseActionFlow",
    "JurisdictionPolicy",
    "AuditEvent",
]
