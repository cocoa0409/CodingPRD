"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3, §4).

Per PRD §2.4 the Applicant, Application, ConsentDisclosure, BackgroundCheckOrder,
Verification, and AdverseAction entities carry id + created_at + updated_at +
version. Jurisdiction, SystemClock, and AuditLog are append-only / config-style
rows that carry only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ─── Status enums ──────────────────────────────────────────────────────

class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONDITIONAL_OFFER = "CONDITIONAL_OFFER"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class BackgroundCheckOrderStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class OverallResult(str, Enum):
    CLEAR = "CLEAR"
    CONSIDER = "CONSIDER"


class VerificationType(str, Enum):
    CRIMINAL = "CRIMINAL"
    MVR = "MVR"
    EDUCATION = "EDUCATION"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED = "REPORTED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class VerificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AdverseActionStatus(str, Enum):
    PRE_ADVERSE_SENT = "PRE_ADVERSE_SENT"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APPLICANT = "Applicant"
    RECRUITER = "Recruiter"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VERIFICATION_PROVIDER = "VerificationProvider"


class RiskScoreVariant(str, Enum):
    PROVISIONAL_IN_REVIEW = "provisional_in_review"
    FINAL_COMPLETE = "final_complete"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Jurisdiction: PRD §2.4 — carries id + created_at only (no updated_at, no version).

class Jurisdiction(TypedDict):
    id: str
    created_at: str
    state_code: str
    ban_the_box_enabled: bool
    salary_history_ban_enabled: bool
    pre_adverse_waiting_days: int


# Applicant, Application, ConsentDisclosure, BackgroundCheckOrder, Verification,
# AdverseAction: PRD §2.4 — full common fields (id, created_at, updated_at, version).

class Applicant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    date_of_birth: str


class Application(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    applicant_id: str
    jurisdiction_id: str
    position_title: str
    salary_history_disclosed: Optional[float]
    status: str
    conditional_offer_at: Optional[str]


class ConsentDisclosure(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    application_id: str
    disclosure_text_version: str
    signed_at: str
    ip_address: str
    consent_status: str


class BackgroundCheckOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    application_id: str
    consent_id: str
    ordered_at: str
    status: str
    overall_result: Optional[str]


class Verification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    verification_type: str
    status: str
    result: Optional[str]
    report_payload: Optional[Dict[str, Any]]
    reported_at: Optional[str]
    disputed_at: Optional[str]


class AdverseAction(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    status: str
    pre_adverse_sent_at: str
    earliest_final_at: str
    finalized_at: Optional[str]
    finalized_by_user_id: Optional[str]
    dispute_reason: Optional[str]


# SystemClock + AuditLog: PRD §2.4 — id + created_at only (no updated_at, no version).

class SystemClock(TypedDict):
    id: str
    created_at: str
    current_utc: str


class AuditLog(TypedDict):
    id: str
    created_at: str
    actor_role: str
    actor_user_id: str
    action: str
    entity_type: str
    entity_id: str
    prior_state: Optional[str]
    new_state: Optional[str]


# Risk-score response (PRD §3.7 — computed read body).

class RiskScoreResponse(TypedDict):
    score: float
    variant: str
    exceeds_threshold: bool
    threshold: float
