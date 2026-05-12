"""Domain types: entity TypedDicts, status enums, role enum.

Sourced from PRD §1 (entities), §2.4 (common fields), §2.1 (roles), and the
state machine sections in §3.1–§3.9. Entities tagged in PRD §2.4 as
exception entities — VolunteerSkill, ActivityRole, AuditLog,
PartnerSyncEvent — carry only id and created_at; their TypedDicts here
deliberately omit updated_at and version.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Roles (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    Volunteer = "Volunteer"
    Organizer = "Organizer"
    SkillAdmin = "SkillAdmin"


# ===========================================================================
# Status enums
# ===========================================================================
class IdentityVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class BackgroundCheckStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class VolunteerSkillReviewStatus(str, Enum):
    SELF_DECLARED = "SELF_DECLARED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActivityStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    RECRUITING = "RECRUITING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SHELVED = "SHELVED"
    REJECTED = "REJECTED"


class ActivityDifficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class HourRuleType(str, Enum):
    ACTUAL_DURATION = "ACTUAL_DURATION"
    FIXED_VALUE = "FIXED_VALUE"
    ROLE_COEFFICIENT = "ROLE_COEFFICIENT"


class SkillSensitivityLevel(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"


class ApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CHECKED_IN = "CHECKED_IN"
    ON_LEAVE = "ON_LEAVE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class HourAdjustmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PointMallItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ARCHIVED = "ARCHIVED"


class RedemptionOrderStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CertificateTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    REISSUED = "REISSUED"


class AuditActionType(str, Enum):
    HOUR_ADJUST_REQUEST = "HOUR_ADJUST_REQUEST"
    HOUR_ADJUST_APPROVE = "HOUR_ADJUST_APPROVE"
    HOUR_ADJUST_REJECT = "HOUR_ADJUST_REJECT"
    CERTIFICATE_ISSUE = "CERTIFICATE_ISSUE"
    CERTIFICATE_REISSUE = "CERTIFICATE_REISSUE"
    CERTIFICATE_REVOKE = "CERTIFICATE_REVOKE"


class PartnerSyncChannel(str, Enum):
    IM = "IM"
    IDENTITY_PROVIDER = "IDENTITY_PROVIDER"
    PARTNER_ORG = "PARTNER_ORG"


# ===========================================================================
# Entities — common-fields entities carry id, created_at, updated_at, version
# (PRD §2.4). Exception entities (VolunteerSkill, ActivityRole, AuditLog,
# PartnerSyncEvent) omit updated_at and version.
# ===========================================================================
class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    id_number_hash: str
    identity_verification_status: str
    background_check_status: str
    home_lat: float
    home_lng: float
    total_service_hours: float
    total_completed_activities: int
    points_balance: int
    archived_hours: float
    created_at: str
    updated_at: str
    version: int


class Skill(TypedDict, total=False):
    id: str
    code: str
    name: str
    requires_certificate: bool
    sensitivity_level: str
    created_at: str
    updated_at: str
    version: int


# VolunteerSkill — PRD §2.4 exception entity (no updated_at, no version).
class VolunteerSkill(TypedDict, total=False):
    id: str
    created_at: str
    volunteer_id: str
    skill_id: str
    certificate_url: Optional[str]
    review_status: str
    reviewed_at: Optional[str]
    reviewer_id: Optional[str]


class Activity(TypedDict, total=False):
    id: str
    organizer_id: str
    title: str
    description: str
    location_lat: float
    location_lng: float
    start_at: str
    end_at: str
    recruit_open_at: str
    recruit_close_at: str
    required_skill_codes: List[str]
    position_quota: int
    filled_positions: int
    difficulty: str
    hour_rule_type: str
    fixed_hour_value: Optional[float]
    requires_sensitive_clearance: bool
    status: str
    site_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ActivityRole — PRD §2.4 exception entity (no updated_at, no version).
class ActivityRole(TypedDict, total=False):
    id: str
    created_at: str
    activity_id: str
    role_label: str
    coefficient: float


class Application(TypedDict, total=False):
    id: str
    activity_id: str
    volunteer_id: str
    activity_role_id: Optional[str]
    distance_km: float
    status: str
    check_in_at: Optional[str]
    check_in_lat: Optional[float]
    check_in_lng: Optional[float]
    check_out_at: Optional[str]
    late_marker: bool
    early_departure_marker: bool
    credited_hours: float
    adjusted_hours: float
    points_awarded: int
    leave_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourAdjustment(TypedDict, total=False):
    id: str
    application_id: str
    requested_by_id: str
    delta_hours: float
    reason: str
    status: str
    approver_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointMallItem(TypedDict, total=False):
    id: str
    sku: str
    name: str
    point_cost: int
    stock: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RedemptionOrder(TypedDict, total=False):
    id: str
    volunteer_id: str
    item_id: str
    quantity: int
    total_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateTemplate(TypedDict, total=False):
    id: str
    code: str
    title: str
    min_hours: float
    min_completed_activities: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    template_id: str
    volunteer_id: str
    serial_number: str
    hours_at_issuance: float
    activities_at_issuance: int
    status: str
    replacement_serial_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog — PRD §2.4 exception entity (no updated_at, no version).
class AuditLog(TypedDict, total=False):
    id: str
    created_at: str
    actor_role: str
    actor_id: str
    action_type: str
    target_entity: str
    target_id: str
    payload: dict


# PartnerSyncEvent — PRD §2.4 exception entity (no updated_at, no version).
class PartnerSyncEvent(TypedDict, total=False):
    id: str
    created_at: str
    channel: str
    event_type: str
    payload: dict


__all__ = [
    "UserRole",
    "IdentityVerificationStatus",
    "BackgroundCheckStatus",
    "VolunteerSkillReviewStatus",
    "ActivityStatus",
    "ActivityDifficulty",
    "HourRuleType",
    "SkillSensitivityLevel",
    "ApplicationStatus",
    "HourAdjustmentStatus",
    "PointMallItemStatus",
    "RedemptionOrderStatus",
    "CertificateTemplateStatus",
    "CertificateStatus",
    "AuditActionType",
    "PartnerSyncChannel",
    "Volunteer",
    "Skill",
    "VolunteerSkill",
    "Activity",
    "ActivityRole",
    "Application",
    "HourAdjustment",
    "PointMallItem",
    "RedemptionOrder",
    "CertificateTemplate",
    "Certificate",
    "AuditLog",
    "PartnerSyncEvent",
]
