"""Domain types: entity TypedDicts, status enums, role enum for the I-9 / E-Verify API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HR_REVIEWER = "HRReviewer"
    EVERIFY_OPERATOR = "EVerifyOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class OnboardingStatus(str, Enum):
    CREATED = "CREATED"
    SECTION1_COMPLETE = "SECTION1_COMPLETE"
    SECTION2_COMPLETE = "SECTION2_COMPLETE"
    EVERIFY_PENDING = "EVERIFY_PENDING"
    AUTHORIZED = "AUTHORIZED"
    TERMINATED_NONCONFIRMED = "TERMINATED_NONCONFIRMED"
    REVERIFICATION_DUE = "REVERIFICATION_DUE"
    EXPIRED_UNAUTHORIZED = "EXPIRED_UNAUTHORIZED"


class CitizenshipStatus(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    NONCITIZEN_NATIONAL = "NONCITIZEN_NATIONAL"
    LPR = "LPR"
    ALIEN_AUTHORIZED = "ALIEN_AUTHORIZED"


class I9FormStatus(str, Enum):
    SECTION1_PENDING = "SECTION1_PENDING"
    SECTION1_DONE = "SECTION1_DONE"
    SECTION2_DONE = "SECTION2_DONE"
    REVERIFIED = "REVERIFIED"


class DocumentPath(str, Enum):
    LIST_A = "LIST_A"
    LIST_B_AND_C = "LIST_B_AND_C"
    UNSET = "UNSET"


class ListCategory(str, Enum):
    LIST_A = "LIST_A"
    LIST_B = "LIST_B"
    LIST_C = "LIST_C"


class IdentityDocumentStatus(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class EVerifyCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    TNC_ISSUED = "TNC_ISSUED"
    REFERRED = "REFERRED"
    EMPLOYMENT_AUTHORIZED = "EMPLOYMENT_AUTHORIZED"
    FINAL_NONCONFIRMATION = "FINAL_NONCONFIRMATION"


class TncType(str, Enum):
    NONE = "NONE"
    SSA_TNC = "SSA_TNC"
    DHS_TNC = "DHS_TNC"


class WorkAuthType(str, Enum):
    EAD = "EAD"
    F1_OPT = "F1_OPT"
    F1_STEM_OPT = "F1_STEM_OPT"
    TPS = "TPS"
    OTHER = "OTHER"


class WorkAuthStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ReverificationReason(str, Enum):
    EXPIRING_AUTH = "EXPIRING_AUTH"
    REHIRE = "REHIRE"
    NAME_CHANGE = "NAME_CHANGE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with id/created_at/updated_at/version are the principal resources;
# AuditEntry is append-only and carries only id + created_at.
# ---------------------------------------------------------------------------
class Onboarding(TypedDict):
    id: str
    employee_full_name: str
    employee_email: str
    citizenship_status: str
    hire_date: str
    work_auth_expiration: Optional[str]
    status: str
    section2_deadline: str
    is_overdue: bool
    requires_everify: bool
    created_at: str
    updated_at: str
    version: int


class I9Form(TypedDict):
    id: str
    onboarding_id: str
    section1_attested_at: Optional[str]
    section1_preparer_used: bool
    chosen_document_path: str
    section2_reviewer_id: Optional[str]
    section2_completed_at: Optional[str]
    current_section3_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IdentityDocument(TypedDict):
    id: str
    onboarding_id: str
    list_category: str
    document_title: str
    document_number: str
    expiration_date: Optional[str]
    is_receipt: bool
    receipt_resolution_deadline: Optional[str]
    accepted_for_section2: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EVerifyCase(TypedDict):
    id: str
    onboarding_id: str
    i9_form_id: str
    submitted_at: Optional[str]
    everify_deadline: str
    was_late: bool
    late_reason: Optional[str]
    tnc_type: str
    tnc_issued_at: Optional[str]
    referral_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkAuthorization(TypedDict):
    id: str
    onboarding_id: str
    auth_type: str
    valid_from: str
    valid_until: str
    stem_extension_applied: bool
    cap_gap_days: int
    effective_valid_until: str
    supersedes_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReverificationEvent(TypedDict):
    id: str
    i9_form_id: str
    work_authorization_id: str
    reverification_reason: str
    new_expiration_date: str
    reviewer_id: str
    completed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only event log: id + created_at only — NO updated_at, NO version.
class AuditEntry(TypedDict):
    id: str
    onboarding_id: str
    actor_role: str
    actor_user_id: str
    action: str
    detail: str
    created_at: str


class RiskSummary(TypedDict):
    risk_score: int
    is_overdue: bool
    open_tnc: bool
