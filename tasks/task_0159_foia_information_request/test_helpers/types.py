"""Domain types: entity TypedDicts, status enums, role enum.

Entities and their lifecycle states track PRD §3. Two entities are
immutable and append-only (ExemptionClaim and AuditEntry per PRD §2.4
and §2.6): "once written they are never updated, and consequently they
carry only id and created_at - both updated_at and version are absent
on those two entities." Their TypedDicts therefore omit updated_at and
version.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    REQUESTER = "Requester"
    OFFICER = "Officer"
    APPEAL_AUTHORITY = "AppealAuthority"
    THIRD_PARTY = "ThirdParty"
    CLOCK_OPERATOR = "ClockOperator"


# ===========================================================================
# Status enums
# ===========================================================================
class RequesterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RequesterTier(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    EDUCATIONAL_NONCOMMERCIAL = "EDUCATIONAL_NONCOMMERCIAL"
    PUBLIC_INTEREST = "PUBLIC_INTEREST"


class RequestStatus(str, Enum):
    INTAKE = "INTAKE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SEARCH = "SEARCH"
    DETERMINATION_PENDING = "DETERMINATION_PENDING"
    RELEASED = "RELEASED"
    PARTIAL_RELEASE = "PARTIAL_RELEASE"
    DENIED = "DENIED"
    GLOMAR_ISSUED = "GLOMAR_ISSUED"
    WITHDRAWN = "WITHDRAWN"
    REOPENED_BY_APPEAL = "REOPENED_BY_APPEAL"


class RecordDisposition(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    RELEASED_FULL = "RELEASED_FULL"
    RELEASED_REDACTED = "RELEASED_REDACTED"
    WITHHELD_FULL = "WITHHELD_FULL"


class ThirdPartyNoticeStatus(str, Enum):
    PENDING_RESPONSE = "PENDING_RESPONSE"
    CONSENTED = "CONSENTED"
    OBJECTED = "OBJECTED"
    EXPIRED = "EXPIRED"
    OVERRIDDEN = "OVERRIDDEN"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


class AppellantRole(str, Enum):
    REQUESTER = "REQUESTER"
    THIRD_PARTY = "THIRD_PARTY"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class FeeAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    ACCEPTED = "ACCEPTED"
    FINALIZED = "FINALIZED"
    WAIVED = "WAIVED"


class ExemptionCode(str, Enum):
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"
    B6 = "B6"
    B7 = "B7"
    B8 = "B8"
    B9 = "B9"


class RedactionScope(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class AuditSubjectType(str, Enum):
    REQUEST = "REQUEST"
    APPEAL = "APPEAL"
    THIRD_PARTY_NOTICE = "THIRD_PARTY_NOTICE"
    FEE_ASSESSMENT = "FEE_ASSESSMENT"


class AuditEventCode(str, Enum):
    INTAKE_RECEIVED = "INTAKE_RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SEARCH_STARTED = "SEARCH_STARTED"
    TOLLING_STARTED = "TOLLING_STARTED"
    TOLLING_ENDED = "TOLLING_ENDED"
    FEE_ESTIMATED = "FEE_ESTIMATED"
    FEE_ACCEPTED = "FEE_ACCEPTED"
    EXEMPTION_CLAIMED = "EXEMPTION_CLAIMED"
    THIRD_PARTY_NOTIFIED = "THIRD_PARTY_NOTIFIED"
    THIRD_PARTY_RESPONDED = "THIRD_PARTY_RESPONDED"
    GLOMAR_ISSUED = "GLOMAR_ISSUED"
    DETERMINATION_ISSUED = "DETERMINATION_ISSUED"
    APPEAL_FILED = "APPEAL_FILED"
    APPEAL_DECIDED = "APPEAL_DECIDED"
    REMANDED = "REMANDED"


# ===========================================================================
# Entity TypedDicts — common-fields entities carry id + created_at +
# updated_at + version. The two append-only entities (ExemptionClaim and
# AuditEntry) carry ONLY id + created_at.
# ===========================================================================
class Requester(TypedDict, total=False):
    id: str
    full_name: str
    contact_email: str
    requester_tier: str
    tier_justification: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Request(TypedDict, total=False):
    id: str
    requester_id: str
    subject_summary: str
    status: str
    fee_estimate_accepted: bool
    fee_waiver_requested: bool
    fee_waiver_granted: Optional[bool]
    glomar_invoked: bool
    glomar_exemption_basis: List[str]
    filed_at: Optional[str]
    response_due_at: Optional[str]
    tolling_days_consumed: int
    determination_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponsiveRecord(TypedDict, total=False):
    id: str
    request_id: str
    title: str
    page_count: int
    contains_third_party_info: bool
    third_party_id: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict, total=False):
    # Append-only — only id and created_at; no updated_at, no version.
    id: str
    record_id: str
    exemption_code: str
    redaction_scope: str
    rationale: str
    created_at: str


class ThirdPartyNotice(TypedDict, total=False):
    id: str
    request_id: str
    record_id: str
    third_party_id: str
    status: str
    response_deadline: Optional[str]
    objection_grounds: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    request_id: str
    appellant_role: str
    grounds: str
    status: str
    filed_at: Optional[str]
    decision_at: Optional[str]
    deciding_officer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    request_id: str
    tier_at_assessment: Optional[str]
    estimated_pages: int
    estimated_search_hours: float
    estimated_review_hours: float
    estimate_total_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEntry(TypedDict, total=False):
    # Append-only — only id and created_at; no updated_at, no version.
    id: str
    subject_type: str
    subject_id: str
    event_code: str
    actor_role: str
    actor_id: str
    payload: Any
    created_at: str


__all__ = [
    "UserRole",
    "RequesterStatus", "RequesterTier",
    "RequestStatus",
    "RecordDisposition",
    "ThirdPartyNoticeStatus",
    "AppealStatus", "AppellantRole", "AppealDecision",
    "FeeAssessmentStatus",
    "ExemptionCode", "RedactionScope",
    "AuditSubjectType", "AuditEventCode",
    "Requester", "Request", "ResponsiveRecord", "ExemptionClaim",
    "ThirdPartyNotice", "Appeal", "FeeAssessment", "AuditEntry",
]
