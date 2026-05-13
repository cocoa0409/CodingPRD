"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Client, Translator, Project, Document, Segment, Assignment,
  TerminologyEntry, QualityScore.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version):
  ProjectTemplate, AuditEntry, ExternalSyncRecord.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    TRANSLATOR = "Translator"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TranslatorGrade(str, Enum):
    JUNIOR = "JUNIOR"
    INTERMEDIATE = "INTERMEDIATE"
    SENIOR = "SENIOR"
    EXPERT = "EXPERT"


class TranslatorAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"


class Domain(str, Enum):
    LEGAL = "LEGAL"
    MEDICAL = "MEDICAL"
    TECH = "TECH"
    MARKETING = "MARKETING"
    MEDIA = "MEDIA"
    FINANCE = "FINANCE"
    GENERAL = "GENERAL"


class ProjectState(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    ALL_TRANSLATED = "ALL_TRANSLATED"
    ALL_REVIEWED = "ALL_REVIEWED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class UrgencyTier(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"
    CRITICAL = "CRITICAL"


class UnitPricingMode(str, Enum):
    PER_WORD = "PER_WORD"
    PER_SEGMENT = "PER_SEGMENT"
    PER_FILE = "PER_FILE"


class FileFormat(str, Enum):
    DOCX = "DOCX"
    PDF = "PDF"
    PPTX = "PPTX"
    XLSX = "XLSX"
    SRT = "SRT"


class SplitMode(str, Enum):
    SENTENCE = "SENTENCE"
    PARAGRAPH = "PARAGRAPH"


class DocumentState(str, Enum):
    UPLOADED = "UPLOADED"
    SPLIT = "SPLIT"
    ARCHIVED = "ARCHIVED"


class SegmentState(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    TRANSLATED = "TRANSLATED"
    REVIEWED = "REVIEWED"
    FINAL_APPROVED = "FINAL_APPROVED"
    REJECTED = "REJECTED"
    REASSIGNED = "REASSIGNED"


class RepetitionClass(str, Enum):
    NEW = "NEW"
    FUZZY = "FUZZY"
    EXACT_REPEAT = "EXACT_REPEAT"
    TM_LEVERAGE = "TM_LEVERAGE"


class AssignmentRole(str, Enum):
    TRANSLATOR = "TRANSLATOR"
    REVIEWER = "REVIEWER"
    FINAL_REVIEWER = "FINAL_REVIEWER"


class AssignmentState(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REASSIGNED = "REASSIGNED"


class TerminologyScopeType(str, Enum):
    PROJECT = "PROJECT"
    CLIENT = "CLIENT"


class TerminologyState(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    CONFLICT = "CONFLICT"
    ARCHIVED = "ARCHIVED"


class QualityScoreState(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class ErrorCategory(str, Enum):
    MISTRANSLATION = "MISTRANSLATION"
    OMISSION = "OMISSION"
    GRAMMAR = "GRAMMAR"
    STYLE = "STYLE"
    TERMINOLOGY = "TERMINOLOGY"


class ErrorSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AuditSubjectType(str, Enum):
    SEGMENT = "Segment"
    ASSIGNMENT = "Assignment"
    PROJECT = "Project"
    QUALITY_SCORE = "QualityScore"


class AuditEvent(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    QUALITY_SCORED = "QUALITY_SCORED"
    REASSIGNED = "REASSIGNED"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


class SyncTargetSystem(str, Enum):
    PAYMENT = "PAYMENT"
    IM = "IM"
    STORAGE = "STORAGE"


class SyncTriggerEvent(str, Enum):
    PROJECT_PUBLISHED = "PROJECT_PUBLISHED"
    PAYMENT_PAYABLE = "PAYMENT_PAYABLE"
    ASSIGNMENT_DISPATCHED = "ASSIGNMENT_DISPATCHED"
    ASSIGNMENT_REJECTED = "ASSIGNMENT_REJECTED"
    STAGE_DEADLINE_BREACHED = "STAGE_DEADLINE_BREACHED"


# ---------------------------------------------------------------------------
# Versioned entities (PRD §2.4)
# ---------------------------------------------------------------------------
class Client(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    tax_rate_bps: int
    payment_cycle_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LanguagePair(TypedDict):
    source_lang: str
    target_lang: str


class Translator(TypedDict, total=False):
    id: str
    display_name: str
    language_pairs: List[Dict[str, str]]
    domains: List[str]
    grade: str
    test_translation_passed: bool
    availability_status: str
    workload_segments_open: int
    rolling_quality_score: float
    latest_quality_score: float
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    source_lang: str
    target_lang: str
    domain: str
    word_count: int
    deadline_at: str
    urgency_tier: str
    unit_pricing_mode: str
    base_unit_price_cents: int
    package_size_segments: int
    template_id: Optional[str]
    state: str
    quoted_total_cents: Optional[int]
    final_payout_cents: Optional[int]
    tax_amount_cents: Optional[int]
    payable_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict, total=False):
    id: str
    project_id: str
    filename: str
    file_format: str
    split_mode: str
    word_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class Segment(TypedDict, total=False):
    id: str
    document_id: str
    project_id: str
    ordinal: int
    source_text: str
    word_count: int
    repetition_class: str
    tm_leverage_pct: int
    translated_text: Optional[str]
    reviewed_text: Optional[str]
    state: str
    assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    project_id: str
    translator_id: str
    role: str
    segment_ids: List[str]
    dispatched_at: str
    accept_deadline_at: str
    stage_deadline_at: Optional[str]
    accepted_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class TerminologyEntry(TypedDict, total=False):
    id: str
    scope_type: str
    scope_id: str
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str
    state: str
    created_at: str
    updated_at: str
    version: int


class QualityScoreErrorItem(TypedDict):
    category: str
    severity: str
    count: int


class QualityScore(TypedDict, total=False):
    id: str
    segment_id: str
    translator_id: str
    errors: List[Dict[str, Any]]
    error_density: float
    score: float
    state: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (id + created_at ONLY; NO updated_at, NO version)
# ---------------------------------------------------------------------------
class ProjectTemplate(TypedDict, total=False):
    id: str
    name: str
    default_domain: str
    default_unit_pricing_mode: str
    default_base_unit_price_cents: int
    default_package_size_segments: int
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    event: str
    from_state: Optional[str]
    to_state: Optional[str]
    actor_role: str
    actor_id: Optional[str]
    payload: Dict[str, Any]
    created_at: str


class ExternalSyncRecord(TypedDict, total=False):
    id: str
    project_id: str
    target_system: str
    trigger_event: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "ClientStatus", "TranslatorGrade", "TranslatorAvailability", "Domain",
    "ProjectState", "UrgencyTier", "UnitPricingMode",
    "FileFormat", "SplitMode", "DocumentState",
    "SegmentState", "RepetitionClass",
    "AssignmentRole", "AssignmentState",
    "TerminologyScopeType", "TerminologyState",
    "QualityScoreState", "ErrorCategory", "ErrorSeverity",
    "AuditSubjectType", "AuditEvent",
    "SyncTargetSystem", "SyncTriggerEvent",
    "Client", "Translator", "Project", "Document", "Segment",
    "Assignment", "TerminologyEntry", "QualityScore",
    "LanguagePair", "QualityScoreErrorItem",
    "ProjectTemplate", "AuditEntry", "ExternalSyncRecord",
]
