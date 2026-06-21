"""Domain types: entity TypedDicts, status enums, role enum.

All field names are taken verbatim from the PRD. Every entity in this system is
mutable and therefore carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    CLERK = "Clerk"
    JUDGE = "Judge"
    ATTORNEY = "Attorney"
    SYSTEM_ADMIN = "SystemAdmin"


# --- Status enums ------------------------------------------------------------
class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    STAYED = "STAYED"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    ON_APPEAL = "ON_APPEAL"
    CLOSED = "CLOSED"


class CasePosture(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CaseType(str, Enum):
    CONTRACT = "CONTRACT"
    TORT = "TORT"
    PROPERTY = "PROPERTY"
    FAMILY = "FAMILY"


class PartyRole(str, Enum):
    PLAINTIFF = "PLAINTIFF"
    DEFENDANT = "DEFENDANT"


class PartyServiceStatus(str, Enum):
    UNSERVED = "UNSERVED"
    SERVED = "SERVED"
    SERVICE_FAILED = "SERVICE_FAILED"


class FilingDocumentType(str, Enum):
    COMPLAINT = "COMPLAINT"
    ANSWER = "ANSWER"
    MOTION = "MOTION"
    EXHIBIT = "EXHIBIT"
    PROOF_OF_SERVICE = "PROOF_OF_SERVICE"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FeeStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ServiceMethod(str, Enum):
    PERSONAL = "PERSONAL"
    MAIL = "MAIL"
    PUBLICATION = "PUBLICATION"


class ServiceStatus(str, Enum):
    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DeadlineType(str, Enum):
    RESPONSE = "RESPONSE"
    DISCOVERY = "DISCOVERY"
    MOTION_HEARING = "MOTION_HEARING"
    STATUTE_OF_LIMITATIONS = "STATUTE_OF_LIMITATIONS"
    APPEAL = "APPEAL"


class AnchorEvent(str, Enum):
    SERVICE_COMPLETED = "SERVICE_COMPLETED"
    FILING_ACCEPTED = "FILING_ACCEPTED"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    CASE_OPENED = "CASE_OPENED"
    MANUAL = "MANUAL"


class CountingMode(str, Enum):
    CALENDAR = "CALENDAR"
    COURT_DAYS = "COURT_DAYS"


class DeadlineStatus(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    MISSED = "MISSED"
    VACATED = "VACATED"


class MotionType(str, Enum):
    DISMISS = "DISMISS"
    SUMMARY_JUDGMENT = "SUMMARY_JUDGMENT"
    CONTINUANCE = "CONTINUANCE"
    COMPEL_DISCOVERY = "COMPEL_DISCOVERY"


class MotionStatus(str, Enum):
    FILED = "FILED"
    UNDER_SUBMISSION = "UNDER_SUBMISSION"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    GRANTED_IN_PART = "GRANTED_IN_PART"
    WITHDRAWN = "WITHDRAWN"


class OrderDisposition(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"
    GRANT_IN_PART = "GRANT_IN_PART"


class FeeWaiverStatus(str, Enum):
    PENDING = "PENDING"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    CANCELLED = "CANCELLED"


class JudgmentType(str, Enum):
    DEFAULT = "DEFAULT"
    SUMMARY = "SUMMARY"
    TRIAL = "TRIAL"
    DISMISSAL = "DISMISSAL"


class JudgmentStatus(str, Enum):
    ENTERED = "ENTERED"
    APPEALED = "APPEALED"
    SATISFIED = "SATISFIED"
    VACATED = "VACATED"


class AppealStatus(str, Enum):
    NOTICE_FILED = "NOTICE_FILED"
    RECORD_PREPARED = "RECORD_PREPARED"
    TRANSMITTED = "TRANSMITTED"
    DISMISSED = "DISMISSED"


# --- Entity TypedDicts -------------------------------------------------------
class Court(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    filing_fee_cents: int
    business_days_only: bool
    holidays: List[str]
    appeal_window_days: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    court_id: str
    case_number: str
    caption: str
    case_type: str
    status: str
    posture: str
    open_deadline_count: int
    total_fees_assessed_cents: int
    total_fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict):
    id: str
    case_id: str
    display_name: str
    role: str
    attorney_user_id: str
    service_status: str
    served_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict):
    id: str
    case_id: str
    filed_by_party_id: str
    document_type: str
    title: str
    status: str
    rejection_reason: Optional[str]
    fee_cents: int
    fee_status: str
    resubmits_filing_id: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceOfProcess(TypedDict):
    id: str
    case_id: str
    filing_id: str
    served_party_id: str
    method: str
    status: str
    service_date: str
    response_due_deadline_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deadline(TypedDict):
    id: str
    case_id: str
    deadline_type: str
    anchor_event: str
    anchor_date: str
    interval_days: int
    counting_mode: str
    due_date: str
    status: str
    parent_deadline_id: Optional[str]
    satisfied_by_filing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Motion(TypedDict):
    id: str
    case_id: str
    filing_id: str
    moving_party_id: str
    motion_type: str
    status: str
    opposed: bool
    hearing_id: Optional[str]
    order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    case_id: str
    motion_id: str
    disposition: str
    text: str
    stays_case: bool
    entered_at: str
    created_at: str
    updated_at: str
    version: int


class FeeWaiver(TypedDict):
    id: str
    case_id: str
    filing_id: str
    requesting_party_id: str
    monthly_income_cents: int
    household_size: int
    status: str
    eligibility_ratio: float
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    case_id: str
    motion_id: Optional[str]
    courtroom: str
    judge_user_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Judgment(TypedDict):
    id: str
    case_id: str
    judgment_type: str
    prevailing_party_id: Optional[str]
    principal_cents: int
    interest_rate_bps: int
    entered_at: str
    total_with_interest_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    case_id: str
    judgment_id: str
    appellant_party_id: str
    filed_on: str
    status: str
    record_page_count: int
    transmittal_fee_cents: int
    transmitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
