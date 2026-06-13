"""Domain types: entity TypedDicts, status enums, role enum.

All primary resources carry common_fields (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    CREDENTIALING_SPECIALIST = "CredentialingSpecialist"
    MEDICAL_DIRECTOR = "MedicalDirector"
    PEER_REVIEWER = "PeerReviewer"
    ENROLLMENT_COORDINATOR = "EnrollmentCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---- Provider status enums ----
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_VERIFICATION = "IN_VERIFICATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"


class CredentialingStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    EXCLUDED = "EXCLUDED"


class RecredState(str, Enum):
    NOT_CLEARED = "NOT_CLEARED"
    CURRENT = "CURRENT"
    RECRED_DUE = "RECRED_DUE"
    IN_RECREDENTIALING = "IN_RECREDENTIALING"


# ---- CredentialItem enums ----
class ItemType(str, Enum):
    STATE_LICENSE = "STATE_LICENSE"
    DEA_REGISTRATION = "DEA_REGISTRATION"
    BOARD_CERTIFICATION = "BOARD_CERTIFICATION"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_PSV = "PENDING_PSV"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ExpirableBand(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    LAPSED = "LAPSED"


# ---- VerificationRequest enums ----
class VerificationMethod(str, Enum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    DESIGNATED_AGENT = "DESIGNATED_AGENT"


class VerificationRequestStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"


# ---- SanctionsScreening enums ----
class ScreeningResult(str, Enum):
    CLEAR = "CLEAR"
    HIT = "HIT"


class ScreeningStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


# ---- SanctionsSource enum ----
class SanctionsSourceCode(str, Enum):
    OIG_LEIE = "OIG_LEIE"
    SAM_EXCLUSIONS = "SAM_EXCLUSIONS"


# ---- CredentialingFile enum ----
class ReviewStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CONDITIONAL = "CONDITIONAL"


# ---- PeerReviewVote enum ----
class Ballot(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


# ---- Payer enums ----
class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


# ---- PayerEnrollment enum ----
class EnrollmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


# =========================================================================
# Entity TypedDicts (all common_fields: true -> id/created_at/updated_at/version)
# =========================================================================
class CredentialingOrg(TypedDict):
    id: str
    name: str
    current_utc: str
    recred_cycle_days: int
    expiring_soon_window_days: int
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    org_id: str
    name: str
    payer_type: str
    retroactive_allowed: bool
    panel_capacity: int
    created_at: str
    updated_at: str
    version: int


class SanctionsSource(TypedDict):
    id: str
    org_id: str
    source_code: str
    severity_weight: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    org_id: str
    npi: str
    caqh_id: Optional[str]
    full_name: str
    specialty: str
    application_status: str
    credentialing_status: str
    recred_state: str
    readiness_score: float
    credentialing_completed_date: Optional[str]
    recred_due_date: Optional[str]
    initiated_by_user_id: Optional[str]
    sanction_score: int
    created_at: str
    updated_at: str
    version: int


class CredentialItem(TypedDict):
    id: str
    provider_id: str
    item_type: str
    identifier: str
    issued_date: str
    expiration_date: str
    verification_state: str
    expirable_band: str
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict):
    id: str
    credential_item_id: str
    provider_id: str
    method: str
    source_reference: str
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanctionsScreening(TypedDict):
    id: str
    provider_id: str
    sanctions_source_id: str
    screened_at: str
    result: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialingFile(TypedDict):
    id: str
    provider_id: str
    review_status: str
    opened_at: Optional[str]
    chair_user_id: Optional[str]
    tally_yes: int
    tally_no: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerReviewer(TypedDict):
    id: str
    org_id: str
    user_id: str
    full_name: str
    vote_weight: int
    created_at: str
    updated_at: str
    version: int


class PeerReviewVote(TypedDict):
    id: str
    credentialing_file_id: str
    reviewer_id: str
    voter_user_id: str
    ballot: str
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayerEnrollment(TypedDict):
    id: str
    provider_id: str
    payer_id: str
    requested_at: str
    effective_date: Optional[str]
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
