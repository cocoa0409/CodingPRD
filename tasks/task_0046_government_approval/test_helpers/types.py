"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: 'Most top-level resources (Department, Matter, MatterVersion,
MaterialTemplate, Application, ReviewTask, CertificateTemplate,
Certificate) carry a uniform set of system-managed fields: id,
created_at, updated_at, version.'

PRD §2.4 also names the log-shaped resources that omit updated_at and
version: 'CorrectionNotice and ExternalEvent and AuditLog all omit both
updated_at and version.'
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ===========================================================================
# Roles (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CATALOG_MANAGER = "CatalogManager"
    REVIEWER = "Reviewer"
    LEAD_REVIEWER = "LeadReviewer"
    CERTIFICATE_OFFICER = "CertificateOfficer"
    APPLICANT = "Applicant"


# ===========================================================================
# Status enums (PRD §3)
# ===========================================================================
class DepartmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MatterStatus(str, Enum):
    DRAFT_ONLY = "DRAFT_ONLY"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class MatterTheme(str, Enum):
    BIRTH = "BIRTH"
    EDUCATION = "EDUCATION"
    BUSINESS = "BUSINESS"
    HOUSING = "HOUSING"
    TRANSPORT = "TRANSPORT"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    OTHER = "OTHER"


class MatterVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class MaterialTemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class MaterialType(str, Enum):
    ORIGINAL = "ORIGINAL"
    COPY = "COPY"
    NOTARIZED = "NOTARIZED"


class CertificateTemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class Channel(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class RoutingMode(str, Enum):
    SERIAL = "SERIAL"
    PARALLEL = "PARALLEL"


class AggregationRule(str, Enum):
    ALL_AGREE = "ALL_AGREE"
    MAJORITY = "MAJORITY"
    LEAD_DECIDES = "LEAD_DECIDES"


class ApplicationReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_CORRECTION = "AWAITING_CORRECTION"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ReviewTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AGREED = "AGREED"
    DISAGREED = "DISAGREED"
    SKIPPED = "SKIPPED"


class CorrectionNoticeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REISSUED = "REISSUED"


class ExternalEventType(str, Enum):
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    SIGNATURE_AFFIXED = "SIGNATURE_AFFIXED"
    PAYMENT_SETTLED = "PAYMENT_SETTLED"
    DATA_SHARED = "DATA_SHARED"


class AuditAction(str, Enum):
    APPLICATION_SUBMIT = "APPLICATION_SUBMIT"
    REVIEW_DECIDE = "REVIEW_DECIDE"
    CORRECTION_ISSUE = "CORRECTION_ISSUE"
    CORRECTION_RESUBMIT = "CORRECTION_RESUBMIT"
    ESCALATE = "ESCALATE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CERT_ISSUE = "CERT_ISSUE"
    CERT_REISSUE = "CERT_REISSUE"
    CERT_REVOKE = "CERT_REVOKE"


class SlaStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ON_TRACK = "ON_TRACK"
    WARNING = "WARNING"
    OVERDUE = "OVERDUE"


class ReviewDecision(str, Enum):
    AGREED = "AGREED"
    DISAGREED = "DISAGREED"


# ===========================================================================
# Entity TypedDicts -- common_fields: true (id + created_at + updated_at +
# version per PRD §2.4).
# ===========================================================================
class Department(TypedDict, total=False):
    id: str
    code: str
    name: str
    parent_department_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict, total=False):
    id: str
    code: str
    theme: str
    owning_department_id: str
    current_published_version_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MatterVersion(TypedDict, total=False):
    id: str
    matter_id: str
    version_label: str
    legal_basis: str
    conditions: str
    required_material_template_ids: List[str]
    statutory_time_limit_days: int
    committed_time_limit_days: int
    warning_threshold_pct: int
    fee_amount_cents: int
    channels: List[str]
    review_routing: Dict[str, Any]
    max_correction_rounds: int
    correction_window_days: int
    certificate_template_id: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialTemplate(TypedDict, total=False):
    id: str
    code: str
    title: str
    material_type: str
    form_url: Optional[str]
    example_url: Optional[str]
    e_form_schema: Optional[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    matter_version_id: str
    applicant_user_id: str
    channel: str
    submitted_materials: List[Dict[str, Any]]
    identity_verified: bool
    payment_status: str
    review_status: str
    correction_round: int
    deadline_at: Optional[str]
    clock_started_at: Optional[str]
    total_paused_seconds: int
    pinned_routing_snapshot: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ReviewTask(TypedDict, total=False):
    id: str
    application_id: str
    department_id: str
    stage_index: int
    is_lead: bool
    status: str
    opinion_text: Optional[str]
    decided_at: Optional[str]
    stage_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificateTemplate(TypedDict, total=False):
    id: str
    code: str
    body_template: str
    required_variables: List[str]
    validity_days: int
    official_seal_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    application_id: str
    certificate_template_id: str
    serial_number: str
    verification_code: str
    rendered_body: str
    issued_at: str
    expires_at: Optional[str]
    status: str
    superseded_by_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Entity TypedDicts -- common_fields: false (id + created_at only). PRD §2.4:
# 'CorrectionNotice and ExternalEvent and AuditLog all omit both updated_at
# and version.'
# ===========================================================================
class CorrectionNotice(TypedDict, total=False):
    id: str
    application_id: str
    round_number: int
    deficiencies: List[Dict[str, Any]]
    issued_by_review_task_id: str
    issued_at: str
    due_at: str
    status: str
    resolved_at: Optional[str]
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    event_type: str
    idempotency_key: str
    subject_application_id: str
    payload: Dict[str, Any]
    processed: bool
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity: str
    target_id: str
    payload_snapshot: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "DepartmentStatus",
    "MatterStatus",
    "MatterTheme",
    "MatterVersionStatus",
    "MaterialTemplateStatus",
    "MaterialType",
    "CertificateTemplateStatus",
    "Channel",
    "RoutingMode",
    "AggregationRule",
    "ApplicationReviewStatus",
    "PaymentStatus",
    "ReviewTaskStatus",
    "CorrectionNoticeStatus",
    "CertificateStatus",
    "ExternalEventType",
    "AuditAction",
    "SlaStatus",
    "ReviewDecision",
    "Department",
    "Matter",
    "MatterVersion",
    "MaterialTemplate",
    "Application",
    "ReviewTask",
    "CertificateTemplate",
    "Certificate",
    "CorrectionNotice",
    "ExternalEvent",
    "AuditLog",
]
