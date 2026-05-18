"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.5 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Petitioner, Beneficiary, Case, Biometrics, RFE, Interview.
- Append-only / immutable entities carrying ONLY id + created_at (plus
  their own immutable fields): CaseTypeConfig, VisaBulletin, CaseEvent.
  PRD §2.5: "a CaseTypeConfig row only carries id and created_at, a
  VisaBulletin row only carries id, created_at, and its own
  published_at field ... and a CaseEvent carries only id, created_at,
  and its own occurred_at".
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PETITIONER = "Petitioner"
    BENEFICIARY = "Beneficiary"
    OFFICER = "Officer"
    SUPERVISOR = "Supervisor"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    BIOMETRICS_SCHEDULED = "BIOMETRICS_SCHEDULED"
    BIOMETRICS_COMPLETED = "BIOMETRICS_COMPLETED"
    RFE_ISSUED = "RFE_ISSUED"
    RFE_RESPONDED = "RFE_RESPONDED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    READY_FOR_DECISION = "READY_FOR_DECISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PriorityDateStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CURRENT = "CURRENT"
    NOT_CURRENT = "NOT_CURRENT"
    RETROGRESSED = "RETROGRESSED"


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


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    FIANCE = "FIANCE"


class BiometricsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class RFEStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class RFEReasonCode(str, Enum):
    MISSING_DOC = "MISSING_DOC"
    IDENTITY_DOC = "IDENTITY_DOC"
    FINANCIAL_PROOF = "FINANCIAL_PROOF"
    MEDICAL_EXAM = "MEDICAL_EXAM"
    TRANSLATION = "TRANSLATION"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class InterviewOutcome(str, Enum):
    RECOMMEND_APPROVAL = "RECOMMEND_APPROVAL"
    RECOMMEND_DENIAL = "RECOMMEND_DENIAL"
    CONTINUED = "CONTINUED"


class DenialReason(str, Enum):
    RFE_TIMEOUT = "RFE_TIMEOUT"
    OFFICER_DENIAL = "OFFICER_DENIAL"
    ABANDONMENT = "ABANDONMENT"
    INELIGIBLE = "INELIGIBLE"


class ChartType(str, Enum):
    FINAL_ACTION = "FINAL_ACTION"
    DATES_FOR_FILING = "DATES_FOR_FILING"


class ReceiptPrefix(str, Enum):
    MSC = "MSC"
    EAC = "EAC"
    WAC = "WAC"
    NBC = "NBC"
    LIN = "LIN"
    SRC = "SRC"
    IOE = "IOE"
    YSC = "YSC"


class CaseEventType(str, Enum):
    STATUS_CHANGED = "STATUS_CHANGED"
    BIOMETRICS_SCHEDULED = "BIOMETRICS_SCHEDULED"
    BIOMETRICS_COMPLETED = "BIOMETRICS_COMPLETED"
    RFE_ISSUED = "RFE_ISSUED"
    RFE_RESPONDED = "RFE_RESPONDED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    BULLETIN_REFRESHED = "BULLETIN_REFRESHED"
    PRIORITY_DATE_RECOMPUTED = "PRIORITY_DATE_RECOMPUTED"
    DECISION_RECORDED = "DECISION_RECORDED"


# ---------------------------------------------------------------------------
# Persisted entities carrying id + created_at + updated_at + version — PRD §2.5
# ---------------------------------------------------------------------------
class Petitioner(TypedDict, total=False):
    id: str
    full_name: str
    a_number: Optional[str]
    date_of_birth: str
    country_of_citizenship: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    petitioner_id: str
    full_name: str
    date_of_birth: str
    country_of_chargeability: str
    preference_category: str
    relationship_to_petitioner: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    petitioner_id: str
    beneficiary_id: str
    case_type: str
    receipt_number: Optional[str]
    priority_date: Optional[str]
    filing_date: Optional[str]
    status: str
    priority_date_status: str
    rfe_deadline: Optional[str]
    linked_i130_case_id: Optional[str]
    decision_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Biometrics(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_at: str
    location_code: str
    status: str
    reschedule_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RFE(TypedDict, total=False):
    id: str
    case_id: str
    issued_at: str
    deadline_at: str
    reason_code: str
    officer_notes: str
    response_received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_at: str
    field_office_code: str
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable entities — id + created_at ONLY (no updated_at,
# no version). PRD §2.5.
# ---------------------------------------------------------------------------
class CaseTypeConfig(TypedDict, total=False):
    id: str
    case_type: str
    requires_biometrics: bool
    requires_interview: bool
    rfe_response_window_days: int
    requires_priority_date_current: bool
    receipt_prefix: str
    created_at: str


class VisaBulletin(TypedDict, total=False):
    id: str
    bulletin_month: str
    chart_type: str
    preference_category: str
    country: str
    cutoff_date: str
    published_at: str
    created_at: str


class CaseEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    from_value: Optional[str]
    to_value: Optional[str]
    actor_role: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "CaseStatus",
    "PriorityDateStatus",
    "CaseType",
    "PreferenceCategory",
    "Relationship",
    "BiometricsStatus",
    "RFEStatus",
    "RFEReasonCode",
    "InterviewStatus",
    "InterviewOutcome",
    "DenialReason",
    "ChartType",
    "ReceiptPrefix",
    "CaseEventType",
    "Petitioner",
    "Beneficiary",
    "Case",
    "Biometrics",
    "RFE",
    "Interview",
    "CaseTypeConfig",
    "VisaBulletin",
    "CaseEvent",
]
