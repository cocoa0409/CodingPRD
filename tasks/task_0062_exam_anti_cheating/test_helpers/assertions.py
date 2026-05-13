"""Entity assertions and domain invariant checkers.

Validates the response-body shape implementers must return for each
entity. Field names match PRD §3 exactly (e.g., 'provisional_score',
'final_score', 'severity_score', 'paper_question_ids',
'identity_verification_count', 'forced_recheck_emitted', 'score_delta').

Append-only archives (PRD §2.4: IdentityVerificationRecord, AbnormalEvent,
AuditLogEntry) MUST NOT carry updated_at / version. Their assertions
explicitly forbid those fields.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Common helpers
# ===========================================================================
def _assert_common_versioned(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: 'Every resource that survives mutation carries the four
    common fields id, created_at, updated_at, and version.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: 'Two entity classes are append-only archives and
    therefore omit updated_at and version entirely, carrying only id and
    created_at.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{label} is append-only — must omit updated_at (PRD §2.4); "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"{label} is append-only — must omit version (PRD §2.4); "
        f"got {data.get('version')!r}"
    )


# ===========================================================================
# Exam
# ===========================================================================
EXAM_STATES = {
    "DRAFT", "OPEN_REGISTRATION", "READY", "IN_SESSION",
    "GRADING", "SCORES_PUBLISHED", "APPEAL_WINDOW", "ARCHIVED",
}


def assert_exam(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Exam")
    assert isinstance(data.get("title"), str) and data["title"], (
        "Exam.title must be a non-empty string"
    )
    assert isinstance(data.get("start_time"), int), (
        "Exam.start_time must be int (unix seconds)"
    )
    assert isinstance(data.get("end_time"), int), (
        "Exam.end_time must be int (unix seconds)"
    )
    assert data["start_time"] < data["end_time"], (
        "Exam.start_time must be strictly less than end_time"
    )
    assert data.get("status") in EXAM_STATES, (
        f"Exam.status invalid: {data.get('status')!r}"
    )
    assert isinstance(data.get("sampling_rule_type"), str), (
        "Exam.sampling_rule_type must be a string"
    )
    assert data["sampling_rule_type"] in {"RANDOM", "STRATIFIED", "BLUEPRINT"}
    assert isinstance(data.get("sampling_rule_spec"), dict)
    assert isinstance(data.get("max_score"), (int, float))
    assert isinstance(data.get("grading_progress_pct"), (int, float))
    assert isinstance(data.get("appeal_window_seconds"), int)


# ===========================================================================
# Question
# ===========================================================================
def assert_question(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Question")
    assert is_valid_uuid(data.get("exam_id", "")), (
        "Question.exam_id must be a UUID"
    )
    assert data.get("question_type") in {
        "SINGLE_CHOICE", "MULTI_CHOICE", "TRUE_FALSE",
        "SHORT_ANSWER", "ESSAY",
    }
    assert data.get("difficulty") in {"EASY", "MEDIUM", "HARD"}
    assert isinstance(data.get("topic"), str)
    assert isinstance(data.get("stem"), str)
    assert isinstance(data.get("max_points"), (int, float))
    assert data["max_points"] > 0, "Question.max_points must be > 0"


# ===========================================================================
# CandidateRegistration
# ===========================================================================
REGISTRATION_STATES = {"REGISTERED", "DISQUALIFIED"}


def assert_registration(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "CandidateRegistration")
    assert is_valid_uuid(data.get("exam_id", ""))
    assert isinstance(data.get("candidate_id"), str) and data["candidate_id"]
    assert isinstance(data.get("id_card_number"), str)
    assert isinstance(data.get("enrolled_at"), int)
    assert data.get("status") in REGISTRATION_STATES


# ===========================================================================
# ExamAttempt
# ===========================================================================
ATTEMPT_STATES = {
    "ENROLLED", "IDENTITY_PENDING", "ACTIVE", "SUSPENDED",
    "SUBMITTED", "GRADED", "FINALIZED", "DISQUALIFIED",
}


def assert_attempt(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "ExamAttempt")
    assert is_valid_uuid(data.get("exam_id", ""))
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data.get("candidate_id"), str) and data["candidate_id"]
    assert data.get("status") in ATTEMPT_STATES, (
        f"ExamAttempt.status invalid: {data.get('status')!r}"
    )
    assert isinstance(data.get("suspended_total_seconds"), int)
    assert data["suspended_total_seconds"] >= 0
    assert isinstance(data.get("identity_verification_count"), int)
    assert data["identity_verification_count"] >= 0
    # Scores are numeric.
    assert isinstance(data.get("provisional_score"), (int, float))
    assert isinstance(data.get("final_score"), (int, float))
    # paper_question_ids is a list (may be empty before composition).
    assert isinstance(data.get("paper_question_ids"), list)


def assert_attempt_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.8 disqualification override: 'when an attempt is
    DISQUALIFIED, its final_score and provisional_score are both forced
    to zero.'"""
    if data.get("status") == "DISQUALIFIED":
        assert data.get("final_score") == 0, (
            "PRD §2.8: DISQUALIFIED attempt must have final_score == 0; "
            f"got {data.get('final_score')!r}"
        )
        assert data.get("provisional_score") == 0, (
            "PRD §2.8: DISQUALIFIED attempt must have provisional_score "
            f"== 0; got {data.get('provisional_score')!r}"
        )


# ===========================================================================
# IdentityVerificationRecord (append-only)
# ===========================================================================
def assert_identity_record(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "IdentityVerificationRecord")
    assert is_valid_uuid(data.get("attempt_id", ""))
    assert data.get("verification_phase") in {"PRE_EXAM", "IN_EXAM_RECHECK"}
    assert data.get("outcome") in {"PASS", "MISMATCH"}
    fr = data.get("factor_results")
    assert isinstance(fr, dict)
    for k in ("id_card", "face", "live_detection"):
        assert k in fr, f"factor_results must contain {k!r} (PRD §3.2)"
        assert isinstance(fr[k], bool)


# ===========================================================================
# AbnormalEvent (append-only)
# ===========================================================================
def assert_abnormal_event(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AbnormalEvent")
    assert is_valid_uuid(data.get("attempt_id", ""))
    assert isinstance(data.get("detected_at"), int)
    assert data.get("monitoring_channel") in {
        "SCREEN", "CAMERA", "AUDIO", "PROCESS", "NETWORK",
    }
    assert data.get("behavior_rule_code") in {
        "FACE_LEAVE", "MULTI_PERSON", "WINDOW_SWITCH", "EXTERNAL_DEVICE",
    }
    assert data.get("marking_mode") in {"REALTIME_ALERT", "AFTER_THE_FACT"}
    assert data.get("severity") in {"INFO", "WARNING", "CRITICAL"}
    assert isinstance(data.get("severity_score"), (int, float))
    assert isinstance(data.get("forced_recheck_emitted"), bool)


# ===========================================================================
# GradingAssignment
# ===========================================================================
GRADING_STATES = {
    "PENDING", "IN_PROGRESS", "SUBMITTED", "RESOLVED", "DISCARDED",
}
BLIND_SLOTS = {"BLIND_A", "BLIND_B", "ARBITRATION"}


def assert_grading_assignment(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "GradingAssignment")
    assert is_valid_uuid(data.get("attempt_id", ""))
    assert is_valid_uuid(data.get("question_id", ""))
    assert data.get("status") in GRADING_STATES, (
        f"GradingAssignment.status invalid: {data.get('status')!r}"
    )
    assert data.get("blind_slot") in BLIND_SLOTS, (
        f"GradingAssignment.blind_slot invalid: {data.get('blind_slot')!r}"
    )


# ===========================================================================
# Appeal
# ===========================================================================
APPEAL_STATES = {
    "SUBMITTED", "UNDER_REVIEW", "DECISION_PENDING", "APPROVED", "REJECTED",
}


def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Appeal")
    assert is_valid_uuid(data.get("attempt_id", ""))
    assert is_valid_uuid(data.get("question_id", ""))
    assert isinstance(data.get("candidate_reason"), str)
    assert data.get("status") in APPEAL_STATES, (
        f"Appeal.status invalid: {data.get('status')!r}"
    )


# ===========================================================================
# AuditLogEntry (append-only)
# ===========================================================================
AUDIT_SUBJECT_TYPES = {
    "EXAM_ATTEMPT", "ABNORMAL_EVENT", "APPEAL", "SCORE_ADJUSTMENT",
}
AUDIT_ACTION_CODES = {
    "ABNORMAL_EVENT_RECORDED", "IDENTITY_MISMATCH", "FORCED_SUBMIT",
    "APPEAL_APPROVED", "SCORE_ADJUSTED",
}


def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLogEntry")
    assert data.get("subject_type") in AUDIT_SUBJECT_TYPES, (
        f"AuditLogEntry.subject_type invalid: {data.get('subject_type')!r}"
    )
    assert isinstance(data.get("subject_id"), str) and data["subject_id"]
    assert data.get("action_code") in AUDIT_ACTION_CODES, (
        f"AuditLogEntry.action_code invalid: {data.get('action_code')!r}"
    )
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    # delta is a free-form before/after pair per PRD §2.9.
    assert isinstance(data.get("delta"), dict)


# ===========================================================================
# Numeric / precision helpers
# ===========================================================================
def assert_two_dp_precision(value: float, label: str = "value") -> None:
    """PRD §2.8: rounding policy 'round half up to two decimal places'."""
    if value is None:
        return
    # Compare against the value rounded to 2 dp; tolerate float noise.
    rounded = round(float(value) + 1e-12, 2)
    assert abs(float(value) - rounded) < 1e-6, (
        f"{label}={value!r} is not rounded to 2 dp"
    )


__all__ = [
    "EXAM_STATES",
    "REGISTRATION_STATES",
    "ATTEMPT_STATES",
    "GRADING_STATES",
    "BLIND_SLOTS",
    "APPEAL_STATES",
    "AUDIT_SUBJECT_TYPES",
    "AUDIT_ACTION_CODES",
    "assert_exam",
    "assert_question",
    "assert_registration",
    "assert_attempt",
    "assert_attempt_invariants",
    "assert_identity_record",
    "assert_abnormal_event",
    "assert_grading_assignment",
    "assert_appeal",
    "assert_audit_entry",
    "assert_two_dp_precision",
]
