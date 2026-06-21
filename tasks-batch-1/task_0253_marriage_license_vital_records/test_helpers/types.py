"""Domain types: entity TypedDicts, status enums, role enum for the
Marriage License & Vital Records API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    OFFICIANT = "Officiant"
    CLERK = "Clerk"
    REGISTRAR = "Registrar"
    WAIVER_OFFICER = "WaiverOfficer"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class LicenseStatus(str, Enum):
    ISSUED = "ISSUED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class ReturnStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecordStatus(str, Enum):
    REGISTERED = "REGISTERED"
    AMENDED = "AMENDED"
    SEALED = "SEALED"


class CopyRequestStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REFUNDED = "REFUNDED"


class AmendmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ApostilleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"


class OfficiantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class PriorMarriageStatus(str, Enum):
    NEVER_MARRIED = "NEVER_MARRIED"
    DIVORCED = "DIVORCED"
    WIDOWED = "WIDOWED"
    MARRIED = "MARRIED"


class CredentialType(str, Enum):
    CLERGY = "CLERGY"
    JUDGE = "JUDGE"
    NOTARY = "NOTARY"
    DEPUTY_COMMISSIONER = "DEPUTY_COMMISSIONER"


class RequesterKind(str, Enum):
    PARTY = "PARTY"
    GOVERNMENT = "GOVERNMENT"
    PUBLIC = "PUBLIC"


class AmendmentType(str, Enum):
    CLERICAL = "CLERICAL"
    SUBSTANTIVE = "SUBSTANTIVE"


class LedgerKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    WAIVE = "WAIVE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true entities carry id + created_at + updated_at + version.
# FeeLedgerEntry is append-only (common_fields: false): id + created_at only.
# ---------------------------------------------------------------------------
class Applicant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    prior_marriage_status: str
    prior_dissolution_date: Optional[str]
    has_judicial_consent: bool
    created_at: str
    updated_at: str
    version: int


class Officiant(TypedDict):
    id: str
    full_name: str
    credential_type: str
    registration_expires_on: str
    status: str
    returns_filed_count: int
    created_at: str
    updated_at: str
    version: int


class MarriageApplication(TypedDict):
    id: str
    applicant_a_id: str
    applicant_b_id: str
    ceremony_county: str
    is_confidential: bool
    status: str
    approved_by_user_id: Optional[str]
    denial_reason_code: Optional[str]
    total_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class MarriageLicense(TypedDict):
    id: str
    application_id: str
    is_confidential: bool
    issued_at: str
    valid_from: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficiantReturn(TypedDict):
    id: str
    license_id: str
    officiant_id: str
    ceremony_date: str
    status: str
    accepted_by_user_id: Optional[str]
    filing_deadline: str
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarriageRecord(TypedDict):
    id: str
    return_id: str
    license_id: str
    is_confidential: bool
    registered_at: str
    status: str
    amendment_count: int
    certified_copies_issued: int
    created_at: str
    updated_at: str
    version: int


class CertifiedCopyRequest(TypedDict):
    id: str
    record_id: str
    requester_kind: str
    copies_requested: int
    fee_waiver_id: Optional[str]
    status: str
    issued_by_user_id: Optional[str]
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AmendmentRequest(TypedDict):
    id: str
    record_id: str
    amendment_type: str
    field_path: str
    new_value: str
    status: str
    resubmit_count: int
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApostilleRequest(TypedDict):
    id: str
    copy_request_id: str
    destination_country: str
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeWaiver(TypedDict):
    id: str
    applicant_id: str
    declared_monthly_income_cents: int
    household_size: int
    status: str
    max_waivable_cents: int
    consumed_cents: int
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeLedgerEntry(TypedDict):
    # Append-only audit row (PRD §2.4): id + created_at ONLY — no updated_at, no version.
    id: str
    application_id: Optional[str]
    kind: str
    amount_cents: int
    source_entity: str
    source_entity_id: str
    created_at: str
