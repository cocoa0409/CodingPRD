"""Domain types: entity TypedDicts, status enums, role enum for the consent & ad-tech compliance API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PRIVACY_ADMIN = "PrivacyAdmin"
    VENDOR_MANAGER = "VendorManager"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    VISITOR = "Visitor"
    ANONYMOUS = "Anonymous"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------

class SaleShareDesignation(str, Enum):
    SELLS_AND_SHARES = "SELLS_AND_SHARES"
    SHARES_ONLY = "SHARES_ONLY"
    NO_SALE_NO_SHARE = "NO_SALE_NO_SHARE"


class PropertyPosture(str, Enum):
    NORMAL = "NORMAL"
    FROZEN = "FROZEN"


class BannerRegime(str, Enum):
    OPT_IN_REQUIRED = "OPT_IN_REQUIRED"
    OPT_OUT_ALLOWED = "OPT_OUT_ALLOWED"
    NOTICE_ONLY = "NOTICE_ONLY"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BannerConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    SUPPRESSED = "SUPPRESSED"
    ARCHIVED = "ARCHIVED"


class VendorStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class TagRuleStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class PurposeCategory(str, Enum):
    NECESSARY = "NECESSARY"
    ANALYTICS = "ANALYTICS"
    ADVERTISING = "ADVERTISING"
    SALE_SHARE = "SALE_SHARE"


class AgeStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ADULT = "ADULT"
    CHILD = "CHILD"


class GpcEffective(str, Enum):
    UNSET = "UNSET"
    ON = "ON"
    OFF = "OFF"


class GpcSignal(str, Enum):
    ON = "ON"
    OFF = "OFF"


class ConsentRecordStatus(str, Enum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SourceOfDecision(str, Enum):
    EXPLICIT_GRANT = "EXPLICIT_GRANT"
    EXPLICIT_WITHDRAW = "EXPLICIT_WITHDRAW"
    AUTO_GPC_WITHDRAW = "AUTO_GPC_WITHDRAW"
    EXPIRY = "EXPIRY"


class ConsentDecision(str, Enum):
    BLOCKED_CHILD = "BLOCKED_CHILD"
    ALWAYS_GRANTED = "ALWAYS_GRANTED"
    EXPLICIT_GRANT = "EXPLICIT_GRANT"
    FORCED_OPT_OUT = "FORCED_OPT_OUT"
    EXPLICIT_WITHDRAWN = "EXPLICIT_WITHDRAWN"
    DENIED_BY_DEFAULT = "DENIED_BY_DEFAULT"
    GRANTED_BY_DEFAULT = "GRANTED_BY_DEFAULT"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PropagationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PROPAGATING = "PROPAGATING"
    ALL_CONFIRMED = "ALL_CONFIRMED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


class VendorPropagationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class ScanStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class ViolationType(str, Enum):
    UNAUTHORIZED_TRACKER = "UNAUTHORIZED_TRACKER"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"


class FindingSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    CLOSED = "CLOSED"


class SweepStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    RESPONDED = "RESPONDED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Property(TypedDict, total=False):
    id: str
    name: str
    sale_share_designation: str
    posture: str
    granted_purpose_count: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionPolicy(TypedDict, total=False):
    id: str
    property_id: str
    jurisdiction_code: str
    banner_regime: str
    min_consent_age: int
    retention_days: int
    gpc_honored: bool
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentBannerConfig(TypedDict, total=False):
    id: str
    property_id: str
    jurisdiction_code: str
    categories_shown: List[str]
    config_label: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    property_id: str
    legal_name: str
    declared_purposes: List[str]
    tracker_signatures: List[str]
    status: str
    risk_score_strict: int
    risk_score_weighted: int
    created_at: str
    updated_at: str
    version: int


class TagRule(TypedDict, total=False):
    id: str
    property_id: str
    vendor_id: str
    banner_config_id: str
    purpose_category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitorProfile(TypedDict, total=False):
    id: str
    property_id: str
    external_ref: str
    jurisdiction_code: str
    attested_birthdate: Optional[str]
    age_status: str
    gpc_effective: str
    gpc_updated_at: Optional[str]
    sale_share_opted_out: bool
    created_at: str
    updated_at: str
    version: int


# Append-only immutable event: id + created_at only (no updated_at, no version)
class GpcSignalEvent(TypedDict, total=False):
    id: str
    visitor_id: str
    signal: str
    created_at: str


class ConsentRecord(TypedDict, total=False):
    id: str
    visitor_id: str
    property_id: str
    purpose_category: str
    status: str
    banner_config_id: Optional[str]
    policy_snapshot_retention_days: int
    last_changed_at: str
    expires_at_pinned: str
    expires_at_rolling: str
    source_of_decision: str
    created_at: str
    updated_at: str
    version: int


class DoNotSellRequest(TypedDict, total=False):
    id: str
    visitor_id: str
    property_id: str
    scope_categories: List[str]
    verification_status: str
    propagation_status: str
    total_propagations: int
    pending_count: int
    confirmed_count: int
    failed_count: int
    created_at: str
    updated_at: str
    version: int


class VendorPropagation(TypedDict, total=False):
    id: str
    request_id: str
    vendor_id: str
    status: str
    attempts: int
    last_attempt_at: str
    created_at: str
    updated_at: str
    version: int


class TagAuditScan(TypedDict, total=False):
    id: str
    property_id: str
    scheduled_start: str
    duration_minutes: int
    status: str
    created_by_user_id: str
    findings_created_count: int
    unauthorized_findings_count: int
    created_at: str
    updated_at: str
    version: int


class TrackerFinding(TypedDict, total=False):
    id: str
    scan_id: str
    tracker_signature: str
    violation_type: str
    severity: str
    vendor_id: Optional[str]
    status: str
    remediated_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatorySweep(TypedDict, total=False):
    id: str
    property_id: str
    regulator_ref: str
    jurisdiction_code: str
    deadline_days: int
    response_due_at: str
    status: str
    escalated_at: Optional[str]
    penalty_exposure_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
