"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HR_PARTNER = "HRPartner"
    EMPLOYEE = "Employee"
    EXTERNAL_AUDITOR = "ExternalAuditor"


class LicenseStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class VerificationPosture(str, Enum):
    NEVER_VERIFIED = "NEVER_VERIFIED"
    CURRENT = "CURRENT"
    OVERDUE = "OVERDUE"


class AlertTier(str, Enum):
    NONE = "NONE"
    T90 = "T90"
    T60 = "T60"
    T30 = "T30"
    AT_EXPIRY = "AT_EXPIRY"


class WorkAuthorization(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    RESTRICTED = "RESTRICTED"


class RestrictionReason(str, Enum):
    SCREENING_FLAGGED = "SCREENING_FLAGGED"
    LICENSE_SUSPENDED = "LICENSE_SUSPENDED"
    LICENSE_LAPSED = "LICENSE_LAPSED"
    VERIFICATION_OVERDUE = "VERIFICATION_OVERDUE"
    MISSING_LICENSE = "MISSING_LICENSE"


class ScreeningPosture(str, Enum):
    CLEAR = "CLEAR"
    PENDING_REVIEW = "PENDING_REVIEW"
    FLAGGED = "FLAGGED"


class ReimbursementMode(str, Enum):
    RECEIPT_BASED = "RECEIPT_BASED"
    FLAT_SCHEDULE = "FLAT_SCHEDULE"


class VerificationSource(str, Enum):
    STATE_BOARD_API = "STATE_BOARD_API"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    NURSYS = "NURSYS"


class VerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    UNREACHABLE = "UNREACHABLE"


class CEActivityStatus(str, Enum):
    LOGGED = "LOGGED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class RenewalRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    MORE_INFO = "MORE_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisciplinaryEventType(str, Enum):
    WARNING = "WARNING"
    REPRIMAND = "REPRIMAND"
    FINE = "FINE"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class DisciplinaryEventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class ListSource(str, Enum):
    OIG_LEIE = "OIG_LEIE"
    SAM_GSA = "SAM_GSA"
    STATE_MEDICAID = "STATE_MEDICAID"


class ScreeningOutcome(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class ScreeningStatus(str, Enum):
    CLOSED_CLEAR = "CLOSED_CLEAR"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    CLEARED_FALSE_POSITIVE = "CLEARED_FALSE_POSITIVE"


class AuditPackageStatus(str, Enum):
    BUILDING = "BUILDING"
    SEALED = "SEALED"
    INVALIDATED = "INVALIDATED"


class LicenseType(TypedDict, total=False):
    id: str
    code: str
    name: str
    ce_hours_required_per_cycle: float
    cycle_length_months: int
    verification_frequency_days: int
    grace_period_days: int
    requires_exclusion_screening: bool
    reimbursement_mode: str
    reimburse_full_up_to_cents: int
    reimburse_half_up_to_cents: int
    flat_schedule_amount_cents: int
    hard_claim_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    work_email: str
    role_code: str
    work_authorization: str
    restriction_reason: Optional[str]
    screening_posture: str
    reimbursement_committed_cents: int
    reimbursement_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class RoleRequirement(TypedDict, total=False):
    id: str
    role_code: str
    license_type_id: str
    state_code: str
    is_required: bool
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    employee_id: str
    license_type_id: str
    state_code: str
    license_number: str
    issued_on: str
    expires_on: str
    status: str
    last_verified_on: Optional[str]
    next_verification_due_on: Optional[str]
    verification_posture: str
    alert_tier: str
    ce_cycle_anchor_on: str
    cycle_ce_hours_validated: float
    rolling_ce_hours_validated: float
    ce_progress_reported_pct: Optional[float]
    ce_progress_required_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class VerificationEvent(TypedDict, total=False):
    # Append-only log: carries ONLY id + created_at, no updated_at, no version.
    id: str
    license_id: str
    verified_on: str
    source: str
    outcome: str
    verifier_user_id: str
    next_verification_due_on: Optional[str]
    created_at: str


class CEActivity(TypedDict, total=False):
    id: str
    license_id: str
    provider_name: str
    activity_title: str
    hours: float
    rounded_hours: float
    completed_on: str
    status: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalRequest(TypedDict, total=False):
    id: str
    license_id: str
    claimed_amount_cents: int
    estimated_reimbursable_cents: int
    expires_on_at_create: str
    approved_amount_cents: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    paid_on: Optional[str]
    info_note: Optional[str]
    decision_note: Optional[str]
    payment_ref: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplinaryEvent(TypedDict, total=False):
    id: str
    license_id: str
    board_case_number: str
    event_type: str
    effective_on: str
    received_via: str
    confirm_at_creation: Optional[bool]
    applied_at_creation: bool
    created_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusionScreening(TypedDict, total=False):
    id: str
    employee_id: str
    list_source: str
    screened_on: str
    outcome: str
    status: str
    valid_until: Optional[str]
    created_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    kind: str
    ref_id: str
    occurred_on: str


class AuditPackage(TypedDict, total=False):
    id: str
    employee_id: str
    period_start: str
    period_end: str
    status: str
    sealed_at: Optional[str]
    evidence_snapshot: List[EvidenceItem]
    evidence_item_count: int
    created_at: str
    updated_at: str
    version: int
