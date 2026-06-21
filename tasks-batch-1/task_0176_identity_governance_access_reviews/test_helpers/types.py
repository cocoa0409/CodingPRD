"""Domain types: entity TypedDicts, status enums, role enum for the
Identity Governance API.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums (PRD §3)
# --------------------------------------------------------------------------
class EntitlementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RoleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SodPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class SodSeverity(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class IdentityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPROVISIONED = "DEPROVISIONED"


class AccessRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GrantLifecycleStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class GrantReviewStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CERTIFIED = "CERTIFIED"
    FLAGGED = "FLAGGED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CampaignPosture(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    COMPLETE = "COMPLETE"


class CertificationItemStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class AuditEventType(str, Enum):
    GRANT_ACTIVATED = "GRANT_ACTIVATED"
    GRANT_REVOKED = "GRANT_REVOKED"
    REQUEST_APPROVED = "REQUEST_APPROVED"
    REQUEST_REJECTED = "REQUEST_REJECTED"
    IDENTITY_DISABLED = "IDENTITY_DISABLED"
    ITEM_CERTIFIED = "ITEM_CERTIFIED"
    ORPHAN_DETECTED = "ORPHAN_DETECTED"


class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    ACCESS_MANAGER = "AccessManager"
    ACCESS_APPROVER = "AccessApprover"
    CAMPAIGN_ADMIN = "CampaignAdmin"
    CERTIFIER = "Certifier"


# --------------------------------------------------------------------------
# Entity TypedDicts — common_fields:true entities carry id/created_at/
# updated_at/version; AuditEvent (common_fields:false) carries only id +
# created_at.
# --------------------------------------------------------------------------
class Entitlement(TypedDict):
    id: str
    name: str
    system_code: str
    is_privileged: bool
    risk_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Role(TypedDict):
    id: str
    name: str
    entitlement_ids: List[str]
    requires_dual_approval: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SodPolicy(TypedDict):
    id: str
    name: str
    entitlement_a_id: str
    entitlement_b_id: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Identity(TypedDict):
    id: str
    display_name: str
    email: str
    is_human: bool
    status: str
    active_grant_count: int
    privileged_entitlement_count: int
    effective_risk_score: int
    projected_risk_score: int
    is_orphan: bool
    created_at: str
    updated_at: str
    version: int


class AccessRequest(TypedDict):
    id: str
    identity_id: str
    role_id: str
    justification: str
    requester_user_id: str
    sod_override_justification: Optional[str]
    status: str
    decided_by_user_id: Optional[str]
    sod_conflict_detected: bool
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict):
    id: str
    identity_id: str
    entitlement_id: str
    source_request_id: Optional[str]
    is_just_in_time: bool
    effective_from: Optional[str]
    effective_until: Optional[str]
    lifecycle_status: str
    review_status: str
    risk_contribution: int
    created_at: str
    updated_at: str
    version: int


class CertificationCampaign(TypedDict):
    id: str
    name: str
    scope_role_id: str
    review_window_start: str
    review_window_end: str
    status: str
    posture: str
    item_count: int
    completion_pct: float
    projected_revocation_count: int
    realized_revocation_count: int
    created_at: str
    updated_at: str
    version: int


class CertificationItem(TypedDict):
    id: str
    campaign_id: str
    grant_id: str
    decision_status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields:false — append-only, immutable: id + created_at only.
class AuditEvent(TypedDict):
    id: str
    subject_identity_id: str
    event_type: str
    actor_user_id: str
    detail: str
    created_at: str
