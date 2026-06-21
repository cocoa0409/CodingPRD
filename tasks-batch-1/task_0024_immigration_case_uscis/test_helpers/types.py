"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3.1 (entities), §3.2–§3.7 (state machines), and §2.1 (roles).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Status enums ─────────────────────────────────────────────


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    BIOMETRICS_SCHEDULED = "BIOMETRICS_SCHEDULED"
    BIOMETRICS_COMPLETED = "BIOMETRICS_COMPLETED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RFE_PENDING = "RFE_PENDING"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ABANDONED = "ABANDONED"


class CaseType(str, Enum):
    I_130 = "I-130"
    I_485 = "I-485"
    I_765 = "I-765"
    I_131 = "I-131"


class PreferenceCategory(str, Enum):
    F1 = "F1"
    F2A = "F2A"
    F2B = "F2B"
    F3 = "F3"
    F4 = "F4"
    IR = "IR"


class Country(str, Enum):
    WORLDWIDE = "WORLDWIDE"
    CHINA = "CHINA"
    INDIA = "INDIA"
    MEXICO = "MEXICO"
    PHILIPPINES = "PHILIPPINES"


class ChartType(str, Enum):
    FINAL_ACTION = "FINAL_ACTION"
    FILING_DATE = "FILING_DATE"


class BiometricsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class InterviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RFEStatus(str, Enum):
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class CaseEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    RFE_ISSUED = "RFE_ISSUED"
    RFE_RESPONDED = "RFE_RESPONDED"
    RFE_EXPIRED = "RFE_EXPIRED"
    BIOMETRICS_COMPLETED = "BIOMETRICS_COMPLETED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    FEE_ASSESSED = "FEE_ASSESSED"
    OFFICER_ASSIGNED = "OFFICER_ASSIGNED"
    VISA_AVAILABILITY_CHECK = "VISA_AVAILABILITY_CHECK"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    APPLICANT = "Applicant"
    ATTORNEY = "Attorney"
    OFFICER = "Officer"
    FIELD_OFFICE_ADMIN = "FieldOfficeAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────
# Entities with common_fields (id + created_at + updated_at + version):
#   Applicant, Attorney, Case, BiometricsAppointment, RFE, InterviewAppointment.
# Append-only / singleton (id + created_at only):
#   VisaBulletinEntry, CaseEvent, ClockState.


class Applicant(TypedDict, total=False):
    id: str
    alien_number: str
    full_name: str
    date_of_birth: str
    country_of_chargeability: str
    email: str
    is_under_14: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict, total=False):
    id: str
    bar_number: str
    full_name: str
    firm_name: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    applicant_id: str
    attorney_id: Optional[str]
    case_type: str
    preference_category: Optional[str]
    receipt_number: Optional[str]
    priority_date: Optional[str]
    file_date: Optional[str]
    status: str
    filing_fee_cents: Optional[int]
    rfe_round_count: int
    assigned_officer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BiometricsAppointment(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_at: str
    asc_location_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RFE(TypedDict, total=False):
    id: str
    case_id: str
    issued_at: str
    response_deadline: str
    evidence_items_requested: List[str]
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterviewAppointment(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_at: str
    field_office_code: str
    status: str
    decision_after_interview: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only / immutable rows — NO updated_at, NO version.

class VisaBulletinEntry(TypedDict, total=False):
    id: str
    bulletin_month: str
    preference_category: str
    country: str
    chart_type: str
    cutoff_date: str
    created_at: str


class CaseEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    payload_json: Any
    occurred_at: str
    created_at: str


class ClockState(TypedDict, total=False):
    id: str
    current_utc: str
    created_at: str
