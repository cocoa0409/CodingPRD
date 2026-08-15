"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SPONSOR_SIGNATORY = "SponsorSignatory"
    BADGING_OFFICER = "BadgingOfficer"
    SECURITY_MANAGER = "SecurityManager"
    AUDITOR = "Auditor"
    ACCESS_CONTROL_SYSTEM = "AccessControlSystem"


class SponsorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BadgeClass(str, Enum):
    SIDA = "SIDA"
    STERILE = "STERILE"
    AOA = "AOA"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    STA_PENDING = "STA_PENDING"
    PENDING_REQUIREMENTS = "PENDING_REQUIREMENTS"
    READY = "READY"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ChrcOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class StaOutcome(str, Enum):
    CLEARED = "CLEARED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    CHRC_FAILED = "CHRC_FAILED"
    STA_DENIED = "STA_DENIED"
    SPONSOR_SUSPENDED = "SPONSOR_SUSPENDED"


class CourseCode(str, Enum):
    SIDA_INITIAL = "SIDA_INITIAL"
    AOA_SAFETY = "AOA_SAFETY"
    AOA_DRIVING = "AOA_DRIVING"
    STERILE_INITIAL = "STERILE_INITIAL"


class BadgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LOST = "LOST"
    STOLEN = "STOLEN"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    VOIDED = "VOIDED"
    RETURNED = "RETURNED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    VIOLATION_POINTS = "VIOLATION_POINTS"
    SPONSOR_SUSPENDED = "SPONSOR_SUSPENDED"


class EscortPrivilegeStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class EscortRevokedReason(str, Enum):
    MANUAL = "MANUAL"
    BADGE_SUSPENDED = "BADGE_SUSPENDED"
    BADGE_DEACTIVATED = "BADGE_DEACTIVATED"
    SUPERSEDED = "SUPERSEDED"


class ZoneCode(str, Enum):
    PUBLIC_TERMINAL = "PUBLIC_TERMINAL"
    STERILE_CONCOURSE = "STERILE_CONCOURSE"
    AOA_MOVEMENT = "AOA_MOVEMENT"
    SECURE_ID_AREA = "SECURE_ID_AREA"


class AccessDecision(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class AccessDenialReason(str, Enum):
    DENIED_NO_BADGE = "DENIED_NO_BADGE"
    DENIED_BADGE_INACTIVE = "DENIED_BADGE_INACTIVE"
    DENIED_ZONE_CLASS = "DENIED_ZONE_CLASS"
    DENIED_ESCORT_NOT_PERMITTED = "DENIED_ESCORT_NOT_PERMITTED"
    DENIED_ESCORT_CAPACITY = "DENIED_ESCORT_CAPACITY"


class ViolationType(str, Enum):
    FAILURE_TO_DISPLAY = "FAILURE_TO_DISPLAY"
    ESCORT_VIOLATION = "ESCORT_VIOLATION"
    UNAUTHORIZED_AREA = "UNAUTHORIZED_AREA"
    SECURITY_BREACH = "SECURITY_BREACH"


class ViolationStatus(str, Enum):
    RECORDED = "RECORDED"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AuditOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


# --- Entity TypedDicts -------------------------------------------------------

class Sponsor(TypedDict):
    id: str
    name: str
    sponsor_code: str
    status: str
    active_badge_quota: int
    active_badge_count: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    sponsor_id: str
    full_name: str
    date_of_birth: str
    government_id_number: str
    created_at: str
    updated_at: str
    version: int


class BadgeApplication(TypedDict):
    id: str
    applicant_id: str
    sponsor_id: str
    badge_class: str
    status: str
    chrc_outcome: Optional[str]
    sta_outcome: Optional[str]
    denial_reason: Optional[str]
    submitted_at: str
    application_expires_at: str
    issued_badge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCompletion(TypedDict):
    # Immutable record: carries only id + created_at (no updated_at, no version).
    id: str
    applicant_id: str
    course_code: str
    completed_at: str
    expires_at: str
    created_at: str


class Badge(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    sponsor_id: str
    badge_number: str
    badge_class: str
    status: str
    issued_at: str
    expires_at: str
    deactivated_at: Optional[str]
    return_deadline: Optional[str]
    returned_at: Optional[str]
    suspended_by: Optional[str]
    suspended_until: Optional[str]
    suspension_reason: Optional[str]
    superseded_by_badge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscortPrivilege(TypedDict):
    id: str
    badge_id: str
    max_escortees: int
    status: str
    granted_by: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessEvent(TypedDict):
    # Append-only log row: carries only id + created_at (no updated_at, no version).
    id: str
    badge_id: Optional[str]
    zone_code: str
    escortee_count: int
    decision: str
    denial_reason: Optional[str]
    occurred_at: str
    created_at: str


class Violation(TypedDict):
    id: str
    badge_id: str
    violation_type: str
    points: int
    occurred_at: str
    status: str
    recorded_by: str
    sustained_by: Optional[str]
    dismissed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerClassRate(TypedDict):
    badge_class: str
    scoped: int
    accounted: int
    rate_pct: float


class AuditCycle(TypedDict):
    id: str
    window_start: str
    window_end: str
    status: str
    scoped_count: Optional[int]
    accounted_count: Optional[int]
    recovery_rate_pct: Optional[float]
    per_class_rates: Optional[List[PerClassRate]]
    outcome: Optional[str]
    due_scoped_count: Optional[int]
    due_accounted_count: Optional[int]
    recovery_rate_provisional_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int
