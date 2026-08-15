"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    RELEASE_MANAGER = "ReleaseManager"
    QA_LEAD = "QALead"
    VENDOR_MANAGER = "VendorManager"
    CERTIFICATION_LEAD = "CertificationLead"
    PLATFORM_REVIEWER = "PlatformReviewer"
    COMPLIANCE_MANAGER = "ComplianceManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class GameTitleStatus(str, Enum):
    CONCEPT = "CONCEPT"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    CERTIFICATION = "CERTIFICATION"
    CERT_APPROVED = "CERT_APPROVED"
    LAUNCHED = "LAUNCHED"
    SUNSET = "SUNSET"


class QaVendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TestPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class TestAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class BuildStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_TEST = "IN_TEST"
    TEST_PASSED = "TEST_PASSED"
    TEST_FAILED = "TEST_FAILED"
    CANDIDATE = "CANDIDATE"
    CONSUMED = "CONSUMED"
    RETIRED = "RETIRED"


class BugReportStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    WONT_FIX = "WONT_FIX"
    DUPLICATE = "DUPLICATE"


class SubmissionPackageStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class CertFindingStatus(str, Enum):
    OPEN = "OPEN"
    FIXED_IN_BUILD = "FIXED_IN_BUILD"
    VERIFIED = "VERIFIED"


class AgeRatingFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    GRANTED = "GRANTED"
    CHALLENGED = "CHALLENGED"


class TranslationStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSLATING = "TRANSLATING"
    LQA = "LQA"
    LOCKED = "LOCKED"


class SignoffStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"


class ReleaseWindowStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class HotfixStatus(str, Enum):
    DECLARED = "DECLARED"
    IN_DEV = "IN_DEV"
    READY_FOR_CERT = "READY_FOR_CERT"
    EXPEDITED_CERT = "EXPEDITED_CERT"
    DEPLOYED = "DEPLOYED"
    ROLLED_BACK = "ROLLED_BACK"


class Platform(str, Enum):
    PS5 = "PS5"
    XSX = "XSX"
    SWITCH2 = "SWITCH2"
    PC = "PC"


# All resources carry the standard system fields of PRD §2.5
# (id, created_at, updated_at, version).

class GameTitle(TypedDict, total=False):
    id: str
    title_code: str
    name: str
    platform_codes: List[str]
    target_launch_date: str
    cert_budget_total_cents: int
    cert_budget_available_cents: int
    cert_budget_escrow_cents: int
    cert_budget_spent_cents: int
    open_blocker_count: int
    hotfix_rollback_count: int
    embargoed: bool
    embargo_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QaVendor(TypedDict, total=False):
    id: str
    name: str
    weekly_capacity_hours: int
    cost_rate_cents_per_hour: int
    status: str
    committed_hours_current_week: int
    available_hours_current_week: int
    escapes_count: int
    created_at: str
    updated_at: str
    version: int


class TestPlan(TypedDict, total=False):
    id: str
    title_id: str
    platform_code: str
    status: str
    entries: List[Dict[str, Any]]
    required_entries_total: int
    covered_required_count: int
    created_at: str
    updated_at: str
    version: int


class TestAssignment(TypedDict, total=False):
    id: str
    vendor_id: str
    plan_id: str
    feature_area: str
    week_start_date: str
    reserved_hours: int
    actual_hours: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Build(TypedDict, total=False):
    id: str
    title_id: str
    platform_code: str
    version_string: str
    patch_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BugReport(TypedDict, total=False):
    id: str
    title_id: str
    build_id: str
    severity: str
    category: str
    found_by_vendor_id: Optional[str]
    regression_of_id: Optional[str]
    is_regression: bool
    found_post_launch: bool
    sla_breached: bool
    reopened_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubmissionPackage(TypedDict, total=False):
    id: str
    title_id: str
    platform_code: str
    build_id: str
    test_plan_id: str
    checklist_id: str
    round: int
    expedited: bool
    fee_cents: Optional[int]
    readiness_optimistic_pct: float
    readiness_strict_pct: float
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    withdrawn_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceChecklist(TypedDict, total=False):
    id: str
    submission_package_id: str
    platform_code: str
    items: List[Dict[str, Any]]
    total_items: int
    passed_count: int
    waived_count: int
    na_count: int
    failed_count: int
    unverified_count: int
    created_at: str
    updated_at: str
    version: int


class CertFinding(TypedDict, total=False):
    id: str
    submission_package_id: str
    severity: str
    requirement_code: str
    description: str
    status: str
    fixed_in_build_id: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class AgeRatingFiling(TypedDict, total=False):
    id: str
    title_id: str
    territory: str
    content_descriptors: List[str]
    fee_cents: Optional[int]
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LocalizationPack(TypedDict, total=False):
    id: str
    title_id: str
    locale: str
    is_required: bool
    text_asset_total: int
    audio_asset_total: int
    translated_text_assets: int
    translated_audio_assets: int
    text_coverage_pct: float
    audio_coverage_pct: float
    translation_status: str
    signoff_status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseWindow(TypedDict, total=False):
    id: str
    title_id: str
    platform_code: str
    kind: str
    start_utc: str
    end_utc: str
    fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CertBlackoutWindow(TypedDict, total=False):
    id: str
    platform_code: str
    start_utc: str
    end_utc: str
    buffer_hours: int
    reason: str
    created_at: str
    updated_at: str
    version: int


class Hotfix(TypedDict, total=False):
    id: str
    title_id: str
    platform_code: str
    build_id: str
    severity: str
    incident_summary: str
    fee_cents: Optional[int]
    expedited_cert_entered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
