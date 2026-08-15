"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3).

Every resource in this API carries the common system-managed fields of PRD
§2.4 (id, created_at, updated_at, version), so every TypedDict below includes
them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SCHEME_ADMIN = "SchemeAdmin"
    CLIENT_ADMIN = "ClientAdmin"
    AUDITOR = "Auditor"
    DECISION_MAKER = "DecisionMaker"
    ANONYMOUS = "Anonymous"


class SchemeCode(str, Enum):
    SQF = "SQF"
    BRC = "BRC"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    DECIDED = "DECIDED"
    CANCELLED = "CANCELLED"


class AuditType(str, Enum):
    INITIAL = "INITIAL"
    SURVEILLANCE = "SURVEILLANCE"
    UNANNOUNCED = "UNANNOUNCED"


class NcGrade(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class NcStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    OVERDUE = "OVERDUE"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    NC_OVERDUE = "NC_OVERDUE"
    CAP_REJECT_LIMIT = "CAP_REJECT_LIMIT"


class ScopeChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class WitnessResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CalibrationStatus(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class ListingStatus(str, Enum):
    LISTED = "LISTED"
    UNLISTED = "UNLISTED"


class DecisionOutcome(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the common fields of PRD §2.4)
# ---------------------------------------------------------------------------

class Scheme(TypedDict):
    id: str
    code: str
    name: str
    supported_category_codes: List[str]
    critical_nc_days: int
    major_nc_days: int
    minor_nc_days: int
    pass_score: int
    unannounced_every_n: int
    unannounced_min_window_days: int
    announced_max_window_days: int
    min_audit_gap_days: int
    cert_validity_days: int
    witness_validity_days: int
    appeal_window_days: int
    max_cap_rejections: int
    rotation_limit: int
    base_fee: float
    per_category_fee: float
    day_rate: float
    unannounced_uplift_pct: float
    high_risk_multiplier: float
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    name: str
    contact_email: str
    country: str
    created_at: str
    updated_at: str
    version: int


class Auditor(TypedDict):
    id: str
    name: str
    competency_categories: List[str]
    conflicted_client_ids: List[str]
    active_audit_count: int
    calibration_status: str
    last_witnessed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DecisionMaker(TypedDict):
    id: str
    name: str
    linked_auditor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CategoryScopeEntry(TypedDict):
    category_code: str
    risk_tier: str


class Application(TypedDict):
    id: str
    client_id: str
    scheme_id: str
    site_name: str
    product_categories: List[CategoryScopeEntry]
    scope_text: str
    status: str
    provisional_fee_quote: Optional[float]
    submitted_at: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    application_id: str
    auditor_id: Optional[str]
    decision_maker_id: Optional[str]
    sequence_number: int
    audit_type: str
    window_start: str
    window_end: str
    status: str
    reported_score: Optional[float]
    resolved_score: Optional[float]
    audit_fee: Optional[float]
    actual_days: Optional[int]
    decision_outcome: Optional[str]
    started_at: Optional[str]
    reported_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Nonconformity(TypedDict):
    id: str
    audit_id: str
    grade: str
    clause_ref: str
    description: str
    status: str
    deadline: str
    cap_text: Optional[str]
    submitted_at: Optional[str]
    rejection_count: int
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    client_id: str
    scheme_id: str
    application_id: str
    audit_id: str
    certificate_number: str
    product_categories: List[CategoryScopeEntry]
    scope_text: str
    valid_from: str
    valid_to: str
    status: str
    suspension_reason: Optional[str]
    status_changed_at: str
    final_fee: float
    created_at: str
    updated_at: str
    version: int


class ScopeChange(TypedDict):
    id: str
    certificate_id: str
    requested_categories: List[CategoryScopeEntry]
    reason: str
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    certificate_id: str
    grounds: str
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WitnessAudit(TypedDict):
    id: str
    auditor_id: str
    witnessed_on: str
    result: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DirectoryListing(TypedDict):
    id: str
    certificate_id: str
    client_name: str
    scheme_code: str
    scope_summary: str
    status: str
    listed_at: str
    unlisted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
