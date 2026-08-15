"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class NurseStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CredentialPosture(str, Enum):
    CLEAR = "CLEAR"
    SCHEDULING_SUSPENDED = "SCHEDULING_SUSPENDED"
    PRACTICE_RESTRICTED = "PRACTICE_RESTRICTED"


class MultistatePrivilegeStatus(str, Enum):
    ELIGIBLE_MULTISTATE = "ELIGIBLE_MULTISTATE"
    SINGLE_STATE_ONLY = "SINGLE_STATE_ONLY"
    NONE = "NONE"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    ENCUMBERED = "ENCUMBERED"
    SURRENDERED = "SURRENDERED"


class PsvStatus(str, Enum):
    REQUESTED = "REQUESTED"
    VERIFIED = "VERIFIED"
    DISCREPANCY = "DISCREPANCY"
    UNREACHABLE = "UNREACHABLE"


class PsvChannel(str, Enum):
    NURSYS = "NURSYS"
    BOARD_PORTAL = "BOARD_PORTAL"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CertType(str, Enum):
    BLS = "BLS"
    ACLS = "ACLS"
    PALS = "PALS"
    CCRN = "CCRN"
    CNOR = "CNOR"
    OCN = "OCN"


class DisciplineStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class DisciplineScope(str, Enum):
    LICENSE = "LICENSE"
    PRIVILEGE = "PRIVILEGE"


class DisciplineActionType(str, Enum):
    REPRIMAND = "REPRIMAND"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class PacketItemType(str, Enum):
    LICENSE_VERIFICATION = "LICENSE_VERIFICATION"
    BLS = "BLS"
    ACLS = "ACLS"
    COMPETENCY_ANNUAL = "COMPETENCY_ANNUAL"
    ATTESTATION = "ATTESTATION"


class PacketItemStatus(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"
    INVALIDATED = "INVALIDATED"


class WindowMode(str, Enum):
    ROLLING = "ROLLING"
    FISCAL = "FISCAL"


class CompletionStatus(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"


class CompletionSource(str, Enum):
    MANUAL = "MANUAL"
    SESSION = "SESSION"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    AUTO_CANCELLED = "AUTO_CANCELLED"


class CancelReason(str, Enum):
    MANUAL = "MANUAL"
    POSTURE_SCHEDULING_SUSPENDED = "POSTURE_SCHEDULING_SUSPENDED"
    POSTURE_PRACTICE_RESTRICTED = "POSTURE_PRACTICE_RESTRICTED"
    NURSE_TERMINATED = "NURSE_TERMINATED"


class TriggerReason(str, Enum):
    MANUAL = "MANUAL"
    PSOR_CHANGE = "PSOR_CHANGE"
    LICENSE_CHANGE = "LICENSE_CHANGE"
    DISCIPLINE_CHANGE = "DISCIPLINE_CHANGE"
    SWEEP = "SWEEP"


class AuditRunStatus(str, Enum):
    INITIATED = "INITIATED"
    FIELD_WORK = "FIELD_WORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class FindingType(str, Enum):
    LICENSE_NOT_CURRENT_IN_WINDOW = "LICENSE_NOT_CURRENT_IN_WINDOW"
    CERTIFICATION_NOT_CURRENT_IN_WINDOW = "CERTIFICATION_NOT_CURRENT_IN_WINDOW"
    COMPETENCY_NOT_CURRENT_IN_WINDOW = "COMPETENCY_NOT_CURRENT_IN_WINDOW"


class EmploymentType(str, Enum):
    STAFF = "STAFF"
    TRAVEL = "TRAVEL"
    PER_DIEM = "PER_DIEM"


class UserRole(str, Enum):
    CREDENTIALING_SPECIALIST = "CredentialingSpecialist"
    PRIMARY_SOURCE_VERIFIER = "PrimarySourceVerifier"
    NURSE_MANAGER = "NurseManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    NURSE = "Nurse"
    SYSTEM_OPERATOR = "SystemOperator"


# --- Entity TypedDicts -------------------------------------------------------
# Every persisted resource carries id, created_at, updated_at, version (PRD §2.4),
# except PrivilegeEvaluation, an append-only event log with only id + created_at.


class Nurse(TypedDict):
    id: str
    full_name: str
    email: str
    primary_state_of_residence: str
    employment_type: str
    hire_date: str
    status: str
    credential_posture: str
    multistate_privilege_status: str
    practice_scope: List[str]
    open_encumbrance_count: int
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict):
    id: str
    nurse_id: str
    state_code: str
    license_number: str
    license_class: str
    multistate_flag: bool
    issued_on: str
    expires_on: str
    status: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrimarySourceVerification(TypedDict):
    id: str
    license_id: str
    channel: str
    status: str
    requested_by_user_id: str
    resolved_by_user_id: Optional[str]
    verified_on: Optional[str]
    valid_through: Optional[str]
    discrepancy_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    nurse_id: str
    cert_type: str
    issuing_body: str
    obtained_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplinaryAction(TypedDict):
    id: str
    nurse_id: str
    license_id: Optional[str]
    scope: str
    action_type: str
    effective_on: str
    status: str
    reported_by_user_id: str
    acknowledged_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialPacket(TypedDict):
    id: str
    nurse_id: str
    target_unit_id: str
    status: str
    readiness_score: float
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PacketItem(TypedDict):
    id: str
    packet_id: str
    item_type: str
    critical: bool
    weight: int
    status: str
    evidence_ref: Optional[str]
    submitted_by_user_id: Optional[str]
    source_credential_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompetencyRequirement(TypedDict):
    id: str
    code: str
    name: str
    validity_months: int
    window_mode: str
    mandatory: bool
    applies_to: List[str]
    created_at: str
    updated_at: str
    version: int


class CompetencyCompletion(TypedDict):
    id: str
    nurse_id: str
    requirement_id: str
    completed_on: str
    expires_on: str
    status: str
    source: str
    session_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    name: str
    required_cert_types: List[str]
    scheduled_hours_total: float
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    nurse_id: str
    unit_id: str
    starts_at: str
    ends_at: str
    hours: float
    status: str
    was_clear_at_start: Optional[bool]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompetencySession(TypedDict):
    id: str
    requirement_id: str
    title: str
    starts_at: str
    ends_at: str
    capacity: int
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class SessionBooking(TypedDict):
    id: str
    session_id: str
    nurse_id: str
    attended: bool
    completion_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrivilegeEvaluation(TypedDict):
    # Append-only event log (PRD §2.4): only id + created_at; no updated_at, no version.
    id: str
    nurse_id: str
    trigger_reason: str
    resulting_status: str
    resulting_scope: List[str]
    home_license_id: Optional[str]
    created_at: str


class AuditRun(TypedDict):
    id: str
    window_start: str
    window_end: str
    per_unit_sample_size: int
    status: str
    sampled_nurse_ids: List[str]
    point_in_time_rate: Optional[float]
    shift_incidence_rate: Optional[float]
    projected_deficiency_count: Optional[float]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_run_id: str
    nurse_id: str
    finding_type: str
    detail: str
    status: str
    created_at: str
    updated_at: str
    version: int
