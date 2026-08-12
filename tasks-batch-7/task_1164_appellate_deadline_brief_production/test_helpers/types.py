"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COURT_ADMIN = "CourtAdmin"
    ATTORNEY = "Attorney"
    COURT_CLERK = "CourtClerk"
    PARALEGAL_STAFF = "ParalegalStaff"


class JurisdictionType(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    TRIBAL = "TRIBAL"


class CasePosture(str, Enum):
    OPEN = "OPEN"
    RECORD_PENDING = "RECORD_PENDING"
    BRIEFING = "BRIEFING"
    ARGUMENT_PENDING = "ARGUMENT_PENDING"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class AppellantSide(str, Enum):
    APPELLANT = "APPELLANT"
    APPELLEE = "APPELLEE"
    CROSS_APPELLANT = "CROSS_APPELLANT"


class AppealEventType(str, Enum):
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    NOTICE_FILED = "NOTICE_FILED"
    POST_JUDGMENT_MOTION_FILED = "POST_JUDGMENT_MOTION_FILED"
    POST_JUDGMENT_MOTION_DECIDED = "POST_JUDGMENT_MOTION_DECIDED"
    RECORD_COMPLETE = "RECORD_COMPLETE"
    BRIEF_FILED = "BRIEF_FILED"
    DECISION_ISSUED = "DECISION_ISSUED"


class DeadlineKind(str, Enum):
    NOTICE_OF_APPEAL = "NOTICE_OF_APPEAL"
    RECORD_DESIGNATION = "RECORD_DESIGNATION"
    TRANSCRIPT_ORDER = "TRANSCRIPT_ORDER"
    OPENING_BRIEF = "OPENING_BRIEF"
    RESPONSE_BRIEF = "RESPONSE_BRIEF"
    REPLY_BRIEF = "REPLY_BRIEF"
    REHEARING_PETITION = "REHEARING_PETITION"
    CERT_PETITION = "CERT_PETITION"


class RecordStatus(str, Enum):
    PENDING_DESIGNATION = "PENDING_DESIGNATION"
    DESIGNATED = "DESIGNATED"
    ASSEMBLING = "ASSEMBLING"
    COMPLETE = "COMPLETE"
    FILED = "FILED"


class TranscriptOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PREPARATION = "IN_PREPARATION"
    DELIVERED = "DELIVERED"
    FILED = "FILED"
    CANCELLED = "CANCELLED"


class BriefingScheduleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    VACATED = "VACATED"


class BriefStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    READY = "READY"
    EFILED = "EFILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STRICKEN = "STRICKEN"


class BriefType(str, Enum):
    OPENING = "OPENING"
    RESPONSE = "RESPONSE"
    REPLY = "REPLY"
    AMICUS = "AMICUS"


class AuthorityType(str, Enum):
    CASE = "CASE"
    STATUTE = "STATUTE"
    RULE = "RULE"
    SECONDARY = "SECONDARY"


class ExtensionTarget(str, Enum):
    OPENING = "OPENING"
    RESPONSE = "RESPONSE"
    REPLY = "REPLY"


class ExtensionMotionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FilingType(str, Enum):
    NOTICE_OF_APPEAL = "NOTICE_OF_APPEAL"
    RECORD = "RECORD"
    BRIEF = "BRIEF"
    EXTENSION_MOTION = "EXTENSION_MOTION"
    REHEARING_PETITION = "REHEARING_PETITION"
    CERT_PETITION = "CERT_PETITION"


class FilingMethod(str, Enum):
    EFILE = "EFILE"
    PAPER = "PAPER"
    HAND = "HAND"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OralArgumentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    WAIVED = "WAIVED"
    CONTINUED = "CONTINUED"


class DecisionOutcome(str, Enum):
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"
    MIXED = "MIXED"


class PetitionType(str, Enum):
    REHEARING = "REHEARING"
    REHEARING_EN_BANC = "REHEARING_EN_BANC"
    CERTIORARI = "CERTIORARI"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class Court(TypedDict, total=False):
    id: str
    code: str
    name: str
    jurisdiction_type: str
    appeal_deadline_days: int
    reply_brief_window_days: int
    uses_word_count: bool
    max_words_opening: int
    max_pages_opening: int
    max_words_reply: int
    max_pages_reply: int
    efiling_required: bool
    weekend_holiday_rollforward: bool
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict, total=False):
    id: str
    bar_number: str
    full_name: str
    email: str
    admitted_court_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    court_id: str
    docket_number: str
    caption: str
    lead_attorney_id: str
    appellant_side: str
    posture: str
    notice_filed_at: Optional[str]
    judgment_entered_at: str
    created_at: str
    updated_at: str
    version: int


class AppealEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    occurred_at: str
    notes: str
    created_at: str
    updated_at: str
    version: int


class Deadline(TypedDict, total=False):
    id: str
    case_id: str
    kind: str
    basis_event_id: str
    provisional_due_at: str
    final_due_at: str
    tolled: bool
    met: bool
    met_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Record(TypedDict, total=False):
    id: str
    case_id: str
    designation_due_at: Optional[str]
    designated_at: Optional[str]
    status: str
    completeness_pct: int
    created_at: str
    updated_at: str
    version: int


class TranscriptOrder(TypedDict, total=False):
    id: str
    record_id: str
    hearing_date: str
    court_reporter: str
    estimated_pages: int
    actual_pages: int
    ordered_at: str
    due_at: str
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BriefingSchedule(TypedDict, total=False):
    id: str
    case_id: str
    opening_due_at: Optional[str]
    response_due_at: Optional[str]
    reply_due_at: Optional[str]
    extensions_granted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Brief(TypedDict, total=False):
    id: str
    case_id: str
    schedule_id: str
    brief_type: str
    author_attorney_id: str
    due_at: Optional[str]
    page_count: int
    word_count: int
    over_limit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TableOfAuthorities(TypedDict, total=False):
    id: str
    brief_id: str
    citation_count: int
    verified_count: int
    unverified_count: int
    generated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict, total=False):
    id: str
    toa_id: str
    raw_text: str
    normalized: str
    authority_type: str
    verified: bool
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionMotion(TypedDict, total=False):
    id: str
    case_id: str
    schedule_id: str
    target: str
    requested_days: int
    reason: str
    granted_days: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict, total=False):
    id: str
    case_id: str
    brief_id: Optional[str]
    filing_type: str
    method: str
    served_party_emails: List[str]
    filed_at: str
    confirmation_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OralArgument(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_start: Optional[str]
    duration_minutes: int
    panel_judges: List[str]
    moot_completed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Decision(TypedDict, total=False):
    id: str
    case_id: str
    outcome: str
    issued_at: str
    mandate_at: str
    rehearing_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class FurtherReviewPetition(TypedDict, total=False):
    id: str
    case_id: str
    petition_type: str
    basis_decision_id: str
    due_at: str
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
