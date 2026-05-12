"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two field-shape classes:

- Resources carrying id, created_at, updated_at, version: AnnotationProject,
  TaskPackage, AnnotatorProfile, QualityInspection, Appeal, PayrollPeriod.

- Append-only entries carrying only id and created_at: GoldenSample,
  AnnotationSubmission, SalaryLedgerEntry, AuditLog, ExternalEvent. Tests
  MUST NOT assert updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    QA_REVIEWER = "QAReviewer"
    ANNOTATOR = "Annotator"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class TaskType(str, Enum):
    CLASSIFICATION = "CLASSIFICATION"
    BBOX = "BBOX"
    SEGMENTATION = "SEGMENTATION"
    KEYPOINT = "KEYPOINT"
    TEXT_NER = "TEXT_NER"
    AUDIO_TRANSCRIPTION = "AUDIO_TRANSCRIPTION"


class Difficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class DistributionMode(str, Enum):
    GRAB = "GRAB"
    DISPATCH = "DISPATCH"
    HYBRID = "HYBRID"


class PackageStatus(str, Enum):
    POOL = "POOL"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    INSPECTING = "INSPECTING"
    APPROVED = "APPROVED"
    REWORK_PENDING = "REWORK_PENDING"
    ARBITRATING = "ARBITRATING"
    REJECTED = "REJECTED"


class AnnotatorTier(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    EXPERT = "EXPERT"


class AnnotatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DISPUTED = "DISPUTED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class AppealDecision(str, Enum):
    UPHOLD = "UPHOLD"
    REJECT = "REJECT"


class ArbitrateDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LedgerKind(str, Enum):
    PIECE_RATE = "PIECE_RATE"
    BONUS = "BONUS"
    PENALTY = "PENALTY"
    ADJUSTMENT_UPHELD = "ADJUSTMENT_UPHELD"
    ADJUSTMENT_REJECTED = "ADJUSTMENT_REJECTED"
    TAX = "TAX"
    WITHHOLD = "WITHHOLD"
    RELEASE = "RELEASE"


class SettlementState(str, Enum):
    WITHHELD = "WITHHELD"
    RELEASED = "RELEASED"


class PayrollPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"


class AuditSubjectKind(str, Enum):
    TASK_PACKAGE = "TASK_PACKAGE"
    SALARY = "SALARY"


class AuditEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    SALARY_ADJUSTMENT = "SALARY_ADJUSTMENT"


class TargetSystem(str, Enum):
    PAYMENT = "PAYMENT"
    IM = "IM"
    STORAGE = "STORAGE"


class DispatchStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class AnnotationProject(TypedDict, total=False):
    id: str
    project_name: str
    task_type: str
    difficulty: str
    guideline_doc_url: str
    sample_preview_urls: List[str]
    package_size: int
    distribution_mode: str
    unit_price_cents: int
    pass_rate_target: float
    timeout_seconds: int
    golden_sample_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at (PRD §2.4)
class GoldenSample(TypedDict, total=False):
    id: str
    project_id: str
    payload_url: str
    expected_label: Any
    created_at: str


class TaskPackage(TypedDict, total=False):
    id: str
    project_id: str
    batch_no: int
    item_count: int
    golden_inserted_count: int
    assigned_annotator_id: Optional[str]
    claimed_at: Optional[str]
    deadline_at: Optional[str]
    rework_round: int
    tier_required: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnotatorProfile(TypedDict, total=False):
    id: str
    display_name: str
    domain_tags: List[str]
    entry_test_score: float
    tier: str
    lifetime_pass_rate: float
    rolling_pass_rate: float
    golden_hit_rate: float
    status: str
    last_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only
class AnnotationSubmission(TypedDict, total=False):
    id: str
    package_id: str
    annotator_id: str
    rework_round: int
    labels: List[Any]
    golden_correct: int
    golden_total: int
    created_at: str


class QualityInspection(TypedDict, total=False):
    id: str
    package_id: str
    submission_id: str
    inspector_id: str
    sample_size: int
    defects_found: int
    pass_rate: float
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    package_id: str
    inspection_id: str
    annotator_id: str
    reason: str
    arbiter_id: Optional[str]
    decision: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only
class SalaryLedgerEntry(TypedDict, total=False):
    id: str
    annotator_id: str
    package_id: Optional[str]
    payroll_period_id: Optional[str]
    kind: str
    gross_amount_cents: int
    settlement_state: str
    created_at: str


class PayrollPeriod(TypedDict, total=False):
    id: str
    cycle_label: str
    opens_at: str
    closes_at: str
    tax_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only
class AuditLog(TypedDict, total=False):
    id: str
    actor_id: str
    actor_role: str
    subject_kind: str
    subject_id: str
    event_type: str
    from_value: Optional[str]
    to_value: Optional[str]
    created_at: str


# Append-only
class ExternalEvent(TypedDict, total=False):
    id: str
    target_system: str
    event_type: str
    payload_ref_id: str
    dispatch_status: str
    created_at: str


__all__ = [
    "UserRole",
    "ProjectStatus",
    "TaskType",
    "Difficulty",
    "DistributionMode",
    "PackageStatus",
    "AnnotatorTier",
    "AnnotatorStatus",
    "InspectionOutcome",
    "AppealStatus",
    "AppealDecision",
    "ArbitrateDecision",
    "LedgerKind",
    "SettlementState",
    "PayrollPeriodStatus",
    "AuditSubjectKind",
    "AuditEventType",
    "TargetSystem",
    "DispatchStatus",
    "AnnotationProject",
    "GoldenSample",
    "TaskPackage",
    "AnnotatorProfile",
    "AnnotationSubmission",
    "QualityInspection",
    "Appeal",
    "SalaryLedgerEntry",
    "PayrollPeriod",
    "AuditLog",
    "ExternalEvent",
]
