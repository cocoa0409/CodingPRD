"""Domain types for the Employee Handbook & Policy Acknowledgment API.

Entity TypedDicts, status enums and the role enum, all named exactly as PRD
§3 and §4 name them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    HR_COMPLIANCE_ADMIN = "HRComplianceAdmin"
    POLICY_AUTHOR = "PolicyAuthor"
    LEGAL_COUNSEL = "LegalCounsel"
    LOCALIZATION_SPECIALIST = "LocalizationSpecialist"
    EMPLOYEE = "Employee"
    PEOPLE_MANAGER = "PeopleManager"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class PolicyCategory(str, Enum):
    CODE_OF_CONDUCT = "CODE_OF_CONDUCT"
    LEAVE = "LEAVE"
    SAFETY = "SAFETY"
    COMPENSATION = "COMPENSATION"
    DATA_PRIVACY = "DATA_PRIVACY"


class PolicyVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LEGAL_REVIEW = "IN_LEGAL_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class AddendumStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class LegalReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    WITHDRAWN = "WITHDRAWN"


class TranslationStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSLATION = "IN_TRANSLATION"
    A11Y_REVIEW = "A11Y_REVIEW"
    PUBLISHED = "PUBLISHED"
    ABANDONED = "ABANDONED"


class ConformanceLevel(str, Enum):
    FAIL = "FAIL"
    AA = "AA"
    AAA = "AAA"


class ReleasePackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AckState(str, Enum):
    UNDELIVERED = "UNDELIVERED"
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXEMPT = "EXEMPT"
    VOIDED = "VOIDED"


class EscalationState(str, Enum):
    NONE = "NONE"
    ESCALATING = "ESCALATING"
    RESOLVED = "RESOLVED"
    MOOT = "MOOT"


class AcknowledgmentMethod(str, Enum):
    ESIGN = "ESIGN"
    WET_SIGNATURE = "WET_SIGNATURE"
    ATTESTED = "ATTESTED"


class AcknowledgmentStatus(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    REVOKED = "REVOKED"


class EscalationCaseStatus(str, Enum):
    OPEN = "OPEN"
    NOTIFIED = "NOTIFIED"
    ESCALATED_HR = "ESCALATED_HR"
    CLOSED_ACKNOWLEDGED = "CLOSED_ACKNOWLEDGED"
    CLOSED_MOOT = "CLOSED_MOOT"
    CLOSED_DISCIPLINARY = "CLOSED_DISCIPLINARY"


class ExceptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MANAGER_APPROVED = "MANAGER_APPROVED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReasonCode(str, Enum):
    RELIGIOUS = "RELIGIOUS"
    MEDICAL = "MEDICAL"
    COLLECTIVE_BARGAINING = "COLLECTIVE_BARGAINING"
    ROLE_CONFLICT = "ROLE_CONFLICT"


class RecordKind(str, Enum):
    CAPTURE = "CAPTURE"
    REVOCATION = "REVOCATION"


# --- Entity shapes -------------------------------------------------------
# Most resources carry id/created_at/updated_at/version.  A release item, an
# acknowledgment event and a retention record are append-only evidence and
# carry ONLY id and created_at (PRD §2.4).


class Jurisdiction(TypedDict):
    id: str
    state_code: str
    display_name: str
    min_legal_review_days: int
    ack_deadline_days: int
    esign_permitted: bool
    proxy_ack_permitted: bool
    retention_years: int
    required_language_codes: List[str]
    ack_window_buffer_days: int
    created_at: str
    updated_at: str
    version: int


class LegalReviewer(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    bar_number: str
    concurrent_review_limit: int
    open_review_count: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    jurisdiction_id: str
    manager_id: Optional[str]
    work_email: str
    full_name: str
    preferred_language_code: str
    needs_accessible_format: bool
    employment_status: str
    open_ack_count: int
    open_escalation_count: int
    created_at: str
    updated_at: str
    version: int


class PolicyDocument(TypedDict):
    id: str
    title: str
    category: str
    owner_user_id: str
    current_published_version_id: Optional[str]
    latest_version_no: int
    max_ack_deadline_days: int
    created_at: str
    updated_at: str
    version: int


class PolicyVersion(TypedDict):
    id: str
    policy_document_id: str
    version_no: int
    body_text: str
    section_count: int
    status: str
    required_jurisdiction_ids: List[str]
    effective_date: Optional[str]
    window_end_date: Optional[str]
    revision_round: int
    approved_at: Optional[str]
    pinned_addendum_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionAddendum(TypedDict):
    id: str
    policy_version_id: str
    jurisdiction_id: str
    body_text: str
    status: str
    approved_by_reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalReview(TypedDict):
    id: str
    policy_version_id: str
    jurisdiction_id: str
    reviewer_id: str
    assigned_at: str
    due_at: str
    status: str
    decided_at: Optional[str]
    round_no: int
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Translation(TypedDict):
    id: str
    policy_version_id: str
    language_code: str
    status: str
    section_scores: List[float]
    a11y_index: Optional[float]
    a11y_round_no: int
    conformance_level: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleasePackage(TypedDict):
    id: str
    name: str
    effective_date: str
    scope_jurisdiction_ids: List[str]
    status: str
    scheduled_at: Optional[str]
    released_at: Optional[str]
    legal_review_deadline: Optional[str]
    roster_snapshot_size: int
    coverage_snapshot_pct: Optional[float]
    coverage_live_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ReleaseItem(TypedDict):
    """Append-only: id + created_at only (PRD §2.4)."""
    id: str
    release_package_id: str
    policy_version_id: str
    supersedes_version_id: Optional[str]
    created_at: str


class DistributionAssignment(TypedDict):
    id: str
    release_package_id: str
    policy_version_id: str
    employee_id: str
    jurisdiction_id: str
    ack_state: str
    escalation_state: str
    window_start_date: str
    due_date: str
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    days_overdue: int
    policy_category: str
    created_at: str
    updated_at: str
    version: int


class Acknowledgment(TypedDict):
    """Append-only: id + created_at only (PRD §2.4)."""
    id: str
    assignment_id: str
    employee_id: str
    method: str
    language_code: str
    signature_text: str
    captured_at: str
    status: str
    revoked_at: Optional[str]
    created_at: str


class EscalationCase(TypedDict):
    id: str
    assignment_id: str
    employee_id: str
    notified_manager_id: Optional[str]
    tier: int
    status: str
    opened_at: str
    closed_at: Optional[str]
    notice_count: int
    created_at: str
    updated_at: str
    version: int


class PolicyException(TypedDict):
    id: str
    employee_id: str
    policy_version_id: str
    assignment_id: str
    approving_manager_id: Optional[str]
    deciding_reviewer_id: Optional[str]
    reason_code: str
    justification: str
    requested_days: int
    prior_exception_count: int
    status: str
    risk_score_conservative: Optional[float]
    risk_score_aggregate: Optional[float]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionRecord(TypedDict):
    """Append-only: id + created_at only (PRD §2.4)."""
    id: str
    acknowledgment_id: str
    employee_id: str
    jurisdiction_id: str
    record_kind: str
    signed_delta: int
    retained_from: str
    retention_until: str
    legal_hold: bool
    hold_reason: Optional[str]
    created_at: str
