"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every common-fields resource carries id, created_at, updated_at,
and version. The following entities are append-only / leaf records that
carry only id + created_at (no updated_at, no version):
    - I9Document
    - ReverificationEvent
    - AuditEvent
    - SystemClock
Their TypedDicts omit updated_at and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    HR_STAFF = "HRStaff"
    EMPLOYER_REP = "EmployerRep"
    SYSTEM = "System"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class CitizenshipStatus(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    NON_CITIZEN_NATIONAL = "NON_CITIZEN_NATIONAL"
    LAWFUL_PERMANENT_RESIDENT = "LAWFUL_PERMANENT_RESIDENT"
    ALIEN_AUTHORIZED = "ALIEN_AUTHORIZED"


class VisaClass(str, Enum):
    F1_OPT = "F1_OPT"
    F1_OPT_STEM = "F1_OPT_STEM"
    H1B = "H1B"
    L1 = "L1"
    TN = "TN"
    OTHER = "OTHER"


class OnboardingStatus(str, Enum):
    PENDING_SECTION_1 = "PENDING_SECTION_1"
    PENDING_SECTION_2 = "PENDING_SECTION_2"
    EVERIFY_PENDING = "EVERIFY_PENDING"
    TNC_OPEN = "TNC_OPEN"
    AUTHORIZED = "AUTHORIZED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    TERMINATED = "TERMINATED"


class FormKind(str, Enum):
    INITIAL = "INITIAL"
    REVERIFICATION = "REVERIFICATION"
    REHIRE = "REHIRE"


class FormStatus(str, Enum):
    DRAFT = "DRAFT"
    SECTION_1_DONE = "SECTION_1_DONE"
    SECTION_2_DONE = "SECTION_2_DONE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class DocumentCategory(str, Enum):
    LIST_A = "LIST_A"
    LIST_B = "LIST_B"
    LIST_C = "LIST_C"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    EMPLOYMENT_AUTHORIZED = "EMPLOYMENT_AUTHORIZED"
    TNC = "TNC"
    FNC = "FNC"
    CLOSED_AUTHORIZED = "CLOSED_AUTHORIZED"
    CLOSED_NOT_AUTHORIZED = "CLOSED_NOT_AUTHORIZED"


class TncKind(str, Enum):
    SSA = "SSA"
    DHS = "DHS"


class TncEmployeeDecision(str, Enum):
    CONTEST = "CONTEST"
    NO_CONTEST = "NO_CONTEST"


class FinalDisposition(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class ReverificationReason(str, Enum):
    WORK_AUTH_EXPIRY = "WORK_AUTH_EXPIRY"
    OPT_TO_OPT_STEM_EXTENSION = "OPT_TO_OPT_STEM_EXTENSION"
    REHIRE_WITHIN_3_YEARS = "REHIRE_WITHIN_3_YEARS"


class EVerifyResult(str, Enum):
    EMPLOYMENT_AUTHORIZED = "EMPLOYMENT_AUTHORIZED"
    TNC = "TNC"
    FNC = "FNC"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# common_fields: true — carries id + created_at + updated_at + version
class Employee(TypedDict, total=False):
    id: str
    legal_name: str
    date_of_birth: str
    ssn: str
    citizenship_status: str
    work_authorization_expiry: Optional[str]
    visa_class: Optional[str]
    start_date: str
    section2_deadline: Optional[str]
    onboarding_status: str
    is_terminated: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class I9Form(TypedDict, total=False):
    id: str
    employee_id: str
    form_kind: str
    supersedes_form_id: Optional[str]
    section1_completed_at: Optional[str]
    section1_attested_by_user_id: Optional[str]
    section2_completed_at: Optional[str]
    section2_completed_by_user_id: Optional[str]
    list_a_document_id: Optional[str]
    list_b_document_id: Optional[str]
    list_c_document_id: Optional[str]
    form_status: str
    reverification_due: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only / leaf record (PRD §2.4)
class I9Document(TypedDict, total=False):
    id: str
    employee_id: str
    category: str
    document_title: str
    document_number: str
    issuing_authority: str
    expiration_date: Optional[str]
    receipt: bool
    receipt_resolution_due: Optional[str]
    created_at: str


# common_fields: true
class EVerifyCase(TypedDict, total=False):
    id: str
    employee_id: str
    i9_form_id: str
    submitted_at: Optional[str]
    idempotency_key: str
    case_status: str
    tnc_kind: Optional[str]
    tnc_opened_at: Optional[str]
    tnc_contest_deadline: Optional[str]
    tnc_employee_decision: Optional[str]
    final_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — leaf record (PRD §2.4)
class ReverificationEvent(TypedDict, total=False):
    id: str
    employee_id: str
    triggering_form_id: str
    reason: str
    new_form_id: Optional[str]
    resolution_deadline: Optional[str]
    resolved_at: Optional[str]
    created_at: str


# common_fields: false — append-only audit row (PRD §2.4, §2.8)
class AuditEvent(TypedDict, total=False):
    id: str
    subject_employee_id: str
    subject_entity: str
    subject_entity_id: str
    action: str
    actor_role: str
    actor_user_id: Optional[str]
    occurred_at: str
    created_at: str


# common_fields: false — system record
class SystemClock(TypedDict, total=False):
    id: str
    current_time: str
    created_at: str


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "CitizenshipStatus",
    "VisaClass",
    "OnboardingStatus",
    "FormKind",
    "FormStatus",
    "DocumentCategory",
    "CaseStatus",
    "TncKind",
    "TncEmployeeDecision",
    "FinalDisposition",
    "ReverificationReason",
    "EVerifyResult",
    # Entities
    "Employee",
    "I9Form",
    "I9Document",
    "EVerifyCase",
    "ReverificationEvent",
    "AuditEvent",
    "SystemClock",
]
