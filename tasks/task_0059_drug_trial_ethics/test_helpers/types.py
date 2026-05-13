"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. PRD §2.4 splits entities into two
shapes:

- Versioned (id + created_at + updated_at + version): Application,
  Submission, CommitteeMember, Meeting, AgendaItem, Resolution,
  Rectification, AnnualReport.

- Append-only (id + created_at ONLY; NO updated_at, NO version):
  ConflictDeclaration, AttendanceConfirmation, Vote, AuditLog.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    SECRETARY = "Secretary"
    CHAIRPERSON = "Chairperson"
    COMMITTEE_MEMBER = "CommitteeMember"
    REGULATORY_WATCHER = "RegulatoryWatcher"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PRESCREEN = "PENDING_PRESCREEN"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    PENDING_REVIEW = "PENDING_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_MOD = "APPROVED_WITH_MOD"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class ApplicationPhase(str, Enum):
    PHASE_I = "PHASE_I"
    PHASE_II = "PHASE_II"
    PHASE_III = "PHASE_III"
    PHASE_IV = "PHASE_IV"


class ReviewTrack(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class PrescreenStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class PrescreenDecision(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class MemberQualification(str, Enum):
    MEDICAL_EXPERT = "MEDICAL_EXPERT"
    PHARMACOLOGIST = "PHARMACOLOGIST"
    ETHICIST = "ETHICIST"
    LEGAL_EXPERT = "LEGAL_EXPERT"
    LAY_REPRESENTATIVE = "LAY_REPRESENTATIVE"
    STATISTICIAN = "STATISTICIAN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


class ConflictType(str, Enum):
    SPONSOR_RELATION = "SPONSOR_RELATION"
    CO_AUTHOR = "CO_AUTHOR"
    ECONOMIC_INTEREST = "ECONOMIC_INTEREST"


class MeetingType(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AGENDA_PUBLISHED = "AGENDA_PUBLISHED"
    IN_SESSION = "IN_SESSION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReviewKind(str, Enum):
    INITIAL_REVIEW = "INITIAL_REVIEW"
    SECONDARY_REVIEW = "SECONDARY_REVIEW"
    ANNUAL_REVIEW = "ANNUAL_REVIEW"
    AMENDMENT_REVIEW = "AMENDMENT_REVIEW"
    FINAL_REPORT_REVIEW = "FINAL_REPORT_REVIEW"


class AgendaItemStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    OPEN_FOR_VOTING = "OPEN_FOR_VOTING"
    CLOSED_WITHOUT_QUORUM = "CLOSED_WITHOUT_QUORUM"
    RESOLVED = "RESOLVED"


class VoteMode(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_MODIFICATION = "APPROVE_WITH_MODIFICATION"
    REJECT = "REJECT"
    DEFER = "DEFER"


class ResolutionOutcome(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_MODIFICATION = "APPROVE_WITH_MODIFICATION"
    REJECT = "REJECT"
    DEFER = "DEFER"
    NO_QUORUM = "NO_QUORUM"


class RectificationStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    UNDER_SECONDARY_REVIEW = "UNDER_SECONDARY_REVIEW"
    CLOSED_APPROVED = "CLOSED_APPROVED"
    CLOSED_REJECTED = "CLOSED_REJECTED"
    EXPIRED = "EXPIRED"


class AnnualReportKind(str, Enum):
    ANNUAL_PROGRESS = "ANNUAL_PROGRESS"
    PROTOCOL_AMENDMENT = "PROTOCOL_AMENDMENT"
    FINAL_REPORT = "FINAL_REPORT"


class AnnualReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED_FOR_REVIEW = "SCHEDULED_FOR_REVIEW"
    RESOLVED = "RESOLVED"


class AnnualReportOutcome(str, Enum):
    CONTINUE = "CONTINUE"
    SUSPEND = "SUSPEND"
    TERMINATE = "TERMINATE"


class AuditEventType(str, Enum):
    REVIEW_DECISION = "REVIEW_DECISION"
    MEMBER_RECUSAL = "MEMBER_RECUSAL"
    REGULATORY_SYNC = "REGULATORY_SYNC"
    IM_NOTIFICATION = "IM_NOTIFICATION"


# ---------------------------------------------------------------------------
# Versioned TypedDicts (PRD §2.4: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Application(TypedDict, total=False):
    id: str
    sponsor_name: str
    drug_name: str
    indication: str
    phase: str
    applicant_id: str
    review_track: str
    status: str
    current_submission_version: int
    approved_submission_version: Optional[int]
    approval_resolution_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    application_id: str
    version_number: int
    protocol_doc_uri: str
    investigator_brochure_uri: str
    informed_consent_uri: str
    cv_doc_uri: str
    checklist_complete: bool
    prescreen_status: str
    prescreen_notes: Optional[str]
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    full_name: str
    qualification: str
    term_start: str
    term_end: str
    is_active: bool
    status: str
    affiliated_sponsors: List[str]
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict, total=False):
    id: str
    meeting_type: str
    scheduled_at: str
    status: str
    agenda_published_at: Optional[str]
    convener_member_id: str
    lead_time_hours: int
    created_at: str
    updated_at: str
    version: int


class AgendaItem(TypedDict, total=False):
    id: str
    meeting_id: str
    application_id: str
    pinned_submission_version: Optional[int]
    review_kind: str
    status: str
    quorum_required: Optional[int]
    eligible_voter_count: Optional[int]
    annual_report_id: Optional[str]
    rectification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Resolution(TypedDict, total=False):
    id: str
    agenda_item_id: str
    application_id: str
    outcome: str
    tally: Dict[str, Any]
    document_uri: str
    pinned_submission_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Rectification(TypedDict, total=False):
    id: str
    application_id: str
    source_resolution_id: str
    opinions: List[str]
    due_at: str
    applicant_response_uri: Optional[str]
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict, total=False):
    id: str
    application_id: str
    report_period_start: str
    report_period_end: str
    report_kind: str
    serious_adverse_event_count: int
    total_adverse_event_count: int
    enrollment_count: int
    outcome: Optional[str]
    safety_alert_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only TypedDicts (PRD §2.4: id + created_at ONLY)
# ---------------------------------------------------------------------------
class ConflictDeclaration(TypedDict, total=False):
    id: str
    member_id: str
    application_id: str
    conflict_type: str
    details: str
    auto_detected: bool
    created_at: str


class AttendanceConfirmation(TypedDict, total=False):
    id: str
    agenda_item_id: str
    member_id: str
    confirmed_at: str
    created_at: str


class Vote(TypedDict, total=False):
    id: str
    agenda_item_id: str
    member_id: str
    vote_mode: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    event_type: str
    subject_entity: str
    subject_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "ApplicationStatus", "ApplicationPhase", "ReviewTrack",
    "PrescreenStatus", "PrescreenDecision",
    "MemberQualification", "MemberStatus", "ConflictType",
    "MeetingType", "MeetingStatus",
    "ReviewKind", "AgendaItemStatus",
    "VoteMode", "ResolutionOutcome",
    "RectificationStatus",
    "AnnualReportKind", "AnnualReportStatus", "AnnualReportOutcome",
    "AuditEventType",
    "Application", "Submission", "CommitteeMember", "Meeting",
    "AgendaItem", "Resolution", "Rectification", "AnnualReport",
    "ConflictDeclaration", "AttendanceConfirmation", "Vote", "AuditLog",
]
