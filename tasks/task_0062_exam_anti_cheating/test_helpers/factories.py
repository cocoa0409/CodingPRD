"""Payload factories — one per endpoint with structured input.

Each factory emits the exact field names declared in PRD §3 prose. For
example, PRD §3.1 specifies the create-exam payload carries `title`,
`start_time`, `end_time`, `appeal_window_seconds`, `per_question_time_limit_seconds`,
`sampling_rule_type`, `sampling_rule_spec`, and `option_shuffle`. PRD §3.4
specifies the abnormal-event payload carries `detected_at`,
`monitoring_channel`, `behavior_rule_code`, `marking_mode`, and
`evidence_clip_uri`.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


# ===========================================================================
# Clock
# ===========================================================================
def clock_advance_payload(to_unix_seconds: int) -> Dict[str, Any]:
    """PRD §2.5: '/_clock/advance ... to a supplied to_unix_seconds
    instant.'"""
    return {"to_unix_seconds": int(to_unix_seconds)}


# ===========================================================================
# Exam (PRD §3.1)
# ===========================================================================
def create_exam_payload(
    title: str = "Test Exam",
    start_time: int = 1000,
    end_time: int = 2000,
    sampling_rule_type: str = "RANDOM",
    sampling_rule_spec: Optional[Dict[str, Any]] = None,
    appeal_window_seconds: Optional[int] = None,
    per_question_time_limit_seconds: Optional[int] = None,
    option_shuffle: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Creation requires a title, a start_time and an
    end_time expressed in unix seconds, and the sampling policy: a
    sampling_rule_type of RANDOM, STRATIFIED, or BLUEPRINT, together
    with a sampling_rule_spec object whose shape depends on the chosen
    mode.'"""
    if sampling_rule_spec is None:
        sampling_rule_spec = {"target_count": 1}
    payload: Dict[str, Any] = {
        "title": title,
        "start_time": int(start_time),
        "end_time": int(end_time),
        "sampling_rule_type": sampling_rule_type,
        "sampling_rule_spec": sampling_rule_spec,
    }
    if appeal_window_seconds is not None:
        payload["appeal_window_seconds"] = int(appeal_window_seconds)
    if per_question_time_limit_seconds is not None:
        payload["per_question_time_limit_seconds"] = int(
            per_question_time_limit_seconds,
        )
    if option_shuffle is not None:
        payload["option_shuffle"] = bool(option_shuffle)
    payload.update(overrides)
    return payload


# ===========================================================================
# Question (PRD §3.1)
# ===========================================================================
def create_objective_question_payload(
    question_type: str = "SINGLE_CHOICE",
    difficulty: str = "EASY",
    topic: str = "general",
    stem: str = "What is 2+2?",
    options: Optional[List[Dict[str, str]]] = None,
    correct_answer: Optional[List[str]] = None,
    max_points: float = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: objective questions (SINGLE_CHOICE / MULTI_CHOICE /
    TRUE_FALSE) carry options + correct_answer; 'objective questions
    must carry no rubric at all.'"""
    if options is None:
        options = [
            {"option_key": "A", "text": "3"},
            {"option_key": "B", "text": "4"},
            {"option_key": "C", "text": "5"},
            {"option_key": "D", "text": "6"},
        ]
    if correct_answer is None:
        correct_answer = ["B"]
    payload: Dict[str, Any] = {
        "question_type": question_type,
        "difficulty": difficulty,
        "topic": topic,
        "stem": stem,
        "options": options,
        "correct_answer": correct_answer,
        "max_points": max_points,
    }
    payload.update(overrides)
    return payload


def create_true_false_question_payload(
    correct_answer: Optional[List[str]] = None,
    max_points: float = 5.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: TRUE_FALSE is objective."""
    return create_objective_question_payload(
        question_type="TRUE_FALSE",
        options=[
            {"option_key": "T", "text": "True"},
            {"option_key": "F", "text": "False"},
        ],
        correct_answer=correct_answer or ["T"],
        max_points=max_points,
        **overrides,
    )


def create_multi_choice_question_payload(
    correct_answer: Optional[List[str]] = None,
    max_points: float = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'multi-choice uses set equality' on correct_answer."""
    return create_objective_question_payload(
        question_type="MULTI_CHOICE",
        correct_answer=correct_answer or ["A", "C"],
        max_points=max_points,
        **overrides,
    )


def create_subjective_question_payload(
    question_type: str = "SHORT_ANSWER",
    difficulty: str = "MEDIUM",
    topic: str = "general",
    stem: str = "Explain X.",
    max_points: float = 10.0,
    rubric: Optional[List[Dict[str, Any]]] = None,
    correct_answer: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Subjective questions additionally require a rubric
    array of { keypoint, points } entries whose points must sum exactly
    to max_points.'"""
    if rubric is None:
        # Default split that sums exactly to max_points.
        rubric = [
            {"keypoint": "kp1", "points": max_points * 0.6},
            {"keypoint": "kp2", "points": max_points * 0.4},
        ]
    if correct_answer is None:
        correct_answer = []
    payload: Dict[str, Any] = {
        "question_type": question_type,
        "difficulty": difficulty,
        "topic": topic,
        "stem": stem,
        "correct_answer": correct_answer,
        "max_points": max_points,
        "rubric": rubric,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# CandidateRegistration (PRD §3.1)
# ===========================================================================
def create_registration_payload(
    candidate_id: str,
    id_card_number: str = "ID-0000000000",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'the administrator submits a candidate's candidate_id
    and id_card_number against the exam, producing a CandidateRegistration
    in status REGISTERED.'"""
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "id_card_number": id_card_number,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# ExamAttempt (PRD §3.2)
# ===========================================================================
def create_attempt_payload(
    registration_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'Creating an attempt requires the candidate to supply
    the registration_id of their own CandidateRegistration.'"""
    payload: Dict[str, Any] = {"registration_id": registration_id}
    payload.update(overrides)
    return payload


# ===========================================================================
# IdentityVerificationRecord (PRD §3.2, §3.4)
# ===========================================================================
def identity_verification_payload(
    verification_phase: str = "PRE_EXAM",
    id_card: bool = True,
    face: bool = True,
    live_detection: bool = True,
    triggered_by_event_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'an IdentityVerificationRecord with verification_phase
    set to PRE_EXAM and a factor_results object whose three boolean
    factors — id_card, face, and live_detection — must each be supplied.'
    PRD §3.4: 'IN_EXAM_RECHECK ... with verification_phase set to
    IN_EXAM_RECHECK and triggered_by_event_id referencing the
    AbnormalEvent.id of the CRITICAL event.'"""
    payload: Dict[str, Any] = {
        "verification_phase": verification_phase,
        "factor_results": {
            "id_card": bool(id_card),
            "face": bool(face),
            "live_detection": bool(live_detection),
        },
    }
    if triggered_by_event_id is not None:
        payload["triggered_by_event_id"] = triggered_by_event_id
    payload.update(overrides)
    return payload


# ===========================================================================
# AbnormalEvent (PRD §3.4)
# ===========================================================================
def abnormal_event_payload(
    detected_at: int,
    monitoring_channel: str = "SCREEN",
    behavior_rule_code: str = "MULTI_PERSON",
    marking_mode: str = "REALTIME_ALERT",
    evidence_clip_uri: Optional[str] = "s3://evidence/clip.mp4",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: payload carries 'detected_at in unix seconds ..., a
    monitoring_channel drawn from SCREEN, CAMERA, AUDIO, PROCESS, or
    NETWORK, a behavior_rule_code drawn from FACE_LEAVE, MULTI_PERSON,
    WINDOW_SWITCH, or EXTERNAL_DEVICE, a marking_mode of either
    REALTIME_ALERT or AFTER_THE_FACT, and an evidence_clip_uri.'"""
    payload: Dict[str, Any] = {
        "detected_at": int(detected_at),
        "monitoring_channel": monitoring_channel,
        "behavior_rule_code": behavior_rule_code,
        "marking_mode": marking_mode,
    }
    if evidence_clip_uri is not None:
        payload["evidence_clip_uri"] = evidence_clip_uri
    payload.update(overrides)
    return payload


# ===========================================================================
# Submit (PRD §3.5)
# ===========================================================================
def submit_attempt_payload(
    answers: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'The optional answers field of the submit payload is
    the candidate's final answer set.'"""
    payload: Dict[str, Any] = {}
    if answers is not None:
        payload["answers"] = answers
    payload.update(overrides)
    return payload


# ===========================================================================
# GradingAssignment scoring (PRD §3.6)
# ===========================================================================
def score_grading_payload(
    awarded_points: float,
    rubric_breakdown: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'the marker scores the assignment by supplying
    awarded_points and a rubric_breakdown array of per-keypoint
    sub-points.'"""
    if rubric_breakdown is None:
        # Default: a single-keypoint breakdown that sums to awarded_points
        # exactly; callers can override for multi-keypoint rubrics.
        rubric_breakdown = [
            {"keypoint": "kp1", "points": awarded_points},
        ]
    payload: Dict[str, Any] = {
        "awarded_points": awarded_points,
        "rubric_breakdown": rubric_breakdown,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Appeal (PRD §3.7)
# ===========================================================================
def create_appeal_payload(
    question_id: str,
    candidate_reason: str = "I believe my answer deserves more credit.",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'The payload references a question_id and a
    candidate_reason.'"""
    payload: Dict[str, Any] = {
        "question_id": question_id,
        "candidate_reason": candidate_reason,
    }
    payload.update(overrides)
    return payload


def secondary_mark_payload(
    secondary_awarded_points: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'The officer supplies secondary_awarded_points.'"""
    payload: Dict[str, Any] = {
        "secondary_awarded_points": secondary_awarded_points,
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(
    decision: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'With decision set to APPROVED ...' / 'With decision
    set to REJECTED ...'"""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


__all__ = [
    "clock_advance_payload",
    "create_exam_payload",
    "create_objective_question_payload",
    "create_true_false_question_payload",
    "create_multi_choice_question_payload",
    "create_subjective_question_payload",
    "create_registration_payload",
    "create_attempt_payload",
    "identity_verification_payload",
    "abnormal_event_payload",
    "submit_attempt_payload",
    "score_grading_payload",
    "create_appeal_payload",
    "secondary_mark_payload",
    "decide_appeal_payload",
]
