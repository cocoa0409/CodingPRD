"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 entity definitions and PRD §2.4 common-field rules.

Append-only archives (PRD §2.4: "IdentityVerificationRecord, AbnormalEvent,
and AuditLogEntry ... omit updated_at and version entirely, carrying only
id and created_at"). Their TypedDicts MUST omit updated_at / version.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ===========================================================================
# Role enum (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    EXAM_ADMIN = "ExamAdmin"
    PROCTOR = "Proctor"
    CANDIDATE = "Candidate"
    MARKER = "Marker"
    APPEAL_OFFICER = "AppealOfficer"
    TEST_HARNESS = "TestHarness"


# ===========================================================================
# Status enums (PRD §3)
# ===========================================================================
class ExamStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_REGISTRATION = "OPEN_REGISTRATION"
    READY = "READY"
    IN_SESSION = "IN_SESSION"
    GRADING = "GRADING"
    SCORES_PUBLISHED = "SCORES_PUBLISHED"
    APPEAL_WINDOW = "APPEAL_WINDOW"
    ARCHIVED = "ARCHIVED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DISQUALIFIED = "DISQUALIFIED"


class AttemptStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IDENTITY_PENDING = "IDENTITY_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    FINALIZED = "FINALIZED"
    DISQUALIFIED = "DISQUALIFIED"


class QuestionType(str, Enum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTI_CHOICE = "MULTI_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    SHORT_ANSWER = "SHORT_ANSWER"
    ESSAY = "ESSAY"


class Difficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class SamplingRuleType(str, Enum):
    RANDOM = "RANDOM"
    STRATIFIED = "STRATIFIED"
    BLUEPRINT = "BLUEPRINT"


class VerificationPhase(str, Enum):
    PRE_EXAM = "PRE_EXAM"
    IN_EXAM_RECHECK = "IN_EXAM_RECHECK"


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    MISMATCH = "MISMATCH"


class MonitoringChannel(str, Enum):
    SCREEN = "SCREEN"
    CAMERA = "CAMERA"
    AUDIO = "AUDIO"
    PROCESS = "PROCESS"
    NETWORK = "NETWORK"


class BehaviorRuleCode(str, Enum):
    FACE_LEAVE = "FACE_LEAVE"
    MULTI_PERSON = "MULTI_PERSON"
    WINDOW_SWITCH = "WINDOW_SWITCH"
    EXTERNAL_DEVICE = "EXTERNAL_DEVICE"


class MarkingMode(str, Enum):
    REALTIME_ALERT = "REALTIME_ALERT"
    AFTER_THE_FACT = "AFTER_THE_FACT"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class GradingAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RESOLVED = "RESOLVED"
    DISCARDED = "DISCARDED"


class BlindSlot(str, Enum):
    BLIND_A = "BLIND_A"
    BLIND_B = "BLIND_B"
    ARBITRATION = "ARBITRATION"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AppealDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditSubjectType(str, Enum):
    EXAM_ATTEMPT = "EXAM_ATTEMPT"
    ABNORMAL_EVENT = "ABNORMAL_EVENT"
    APPEAL = "APPEAL"
    SCORE_ADJUSTMENT = "SCORE_ADJUSTMENT"


class AuditActionCode(str, Enum):
    ABNORMAL_EVENT_RECORDED = "ABNORMAL_EVENT_RECORDED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    FORCED_SUBMIT = "FORCED_SUBMIT"
    APPEAL_APPROVED = "APPEAL_APPROVED"
    SCORE_ADJUSTED = "SCORE_ADJUSTED"


# ===========================================================================
# Entity TypedDicts. PRD §2.4: entities with common_fields carry id +
# created_at + updated_at + version; the three append-only archives
# (IdentityVerificationRecord, AbnormalEvent, AuditLogEntry) carry ONLY id
# + created_at.
# ===========================================================================
class Exam(TypedDict, total=False):
    id: str
    title: str
    start_time: int
    end_time: int
    appeal_window_seconds: int
    per_question_time_limit_seconds: int
    sampling_rule_type: str
    sampling_rule_spec: Dict[str, Any]
    option_shuffle: bool
    max_score: float
    grading_progress_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Question(TypedDict, total=False):
    id: str
    exam_id: str
    question_type: str
    difficulty: str
    topic: str
    stem: str
    options: List[Dict[str, str]]
    correct_answer: List[str]
    max_points: float
    rubric: Optional[List[Dict[str, Any]]]
    created_at: str
    updated_at: str
    version: int


class CandidateRegistration(TypedDict, total=False):
    id: str
    exam_id: str
    candidate_id: str
    id_card_number: str
    enrolled_at: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict, total=False):
    id: str
    exam_id: str
    registration_id: str
    candidate_id: str
    paper_version_hash: Optional[str]
    paper_question_ids: List[str]
    paper_option_order: Dict[str, List[str]]
    started_at: Optional[int]
    submitted_at: Optional[int]
    suspended_total_seconds: int
    current_suspend_started_at: Optional[int]
    provisional_score: float
    final_score: float
    identity_verification_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only archive: only id + created_at, plus its own data fields.
class IdentityVerificationRecord(TypedDict, total=False):
    id: str
    attempt_id: str
    verification_phase: str
    factor_results: Dict[str, bool]
    outcome: str
    triggered_by_event_id: Optional[str]
    created_at: str


# Append-only archive: only id + created_at, plus its own data fields.
class AbnormalEvent(TypedDict, total=False):
    id: str
    attempt_id: str
    detected_at: int
    monitoring_channel: str
    behavior_rule_code: str
    severity: str
    severity_score: float
    marking_mode: str
    evidence_clip_uri: Optional[str]
    forced_recheck_emitted: bool
    created_at: str


class GradingAssignment(TypedDict, total=False):
    id: str
    attempt_id: str
    question_id: str
    marker_id: Optional[str]
    blind_slot: str
    candidate_answer_snapshot: Optional[str]
    awarded_points: Optional[float]
    rubric_breakdown: Optional[List[Dict[str, Any]]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    attempt_id: str
    exam_id: str
    question_id: str
    candidate_reason: str
    secondary_awarded_points: Optional[float]
    decision: Optional[str]
    score_delta: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only archive: only id + created_at, plus its own data fields.
class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    action_code: str
    delta: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "ExamStatus",
    "RegistrationStatus",
    "AttemptStatus",
    "QuestionType",
    "Difficulty",
    "SamplingRuleType",
    "VerificationPhase",
    "VerificationOutcome",
    "MonitoringChannel",
    "BehaviorRuleCode",
    "MarkingMode",
    "Severity",
    "GradingAssignmentStatus",
    "BlindSlot",
    "AppealStatus",
    "AppealDecision",
    "AuditSubjectType",
    "AuditActionCode",
    "Exam",
    "Question",
    "CandidateRegistration",
    "ExamAttempt",
    "IdentityVerificationRecord",
    "AbnormalEvent",
    "GradingAssignment",
    "Appeal",
    "AuditLogEntry",
]
