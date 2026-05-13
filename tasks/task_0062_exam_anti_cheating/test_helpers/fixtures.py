"""Composite setup helpers for the Exam Anti-Cheating test suite.

The PRD scenarios are long-lived (DRAFT → OPEN_REGISTRATION → READY →
IN_SESSION → GRADING → SCORES_PUBLISHED → APPEAL_WINDOW → ARCHIVED for the
Exam, plus the ExamAttempt's own ENROLLED → IDENTITY_PENDING → ACTIVE →
SUSPENDED → SUBMITTED → GRADED → FINALIZED lattice, with cycles in the
Active/Suspended pair and the GradingAssignment arbitration loop). Most
useful test claims need 10–25 API calls to set up. These helpers
encapsulate those preambles.

PRD §2.1 identity threading (LOAD-BEARING):

  The Candidate role is entity_backed:CandidateRegistration. Every
  ownership-gated Candidate call (attempt creation, begin-identity-check,
  identity-verifications, network-disconnect/resume, submit, appeal
  creation) MUST use make_candidate_headers(<candidate_id>) where
  <candidate_id> is the exact candidate_id used at registration creation.
  Falling back to TEST_USERS['candidate_headers'] would set X-User-ID to
  'candidate-fallback', which does not equal any real candidate_id, so
  the ownership traversal (attempt → registration → candidate_id) would
  reject every call.

  Therefore every fixture in this module that creates a registration
  remembers the candidate_id it used and passes it through to
  make_candidate_headers() for every subsequent candidate call.

Setup helpers use get_success_data (lenient validator) so a broken
precondition surfaces as a clear setup error rather than a confusing
assertion failure inside the test body.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    abnormal_event_payload,
    clock_advance_payload,
    create_appeal_payload,
    create_attempt_payload,
    create_exam_payload,
    create_objective_question_payload,
    create_registration_payload,
    create_subjective_question_payload,
    decide_appeal_payload,
    identity_verification_payload,
    score_grading_payload,
    secondary_mark_payload,
    submit_attempt_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeal_officer_headers,
    make_candidate_headers,
    make_marker_headers,
)


# ===========================================================================
# Shared opaque-role headers
# ===========================================================================
EXAM_ADMIN = TEST_USERS["exam_admin_headers"]
PROCTOR = TEST_USERS["proctor_headers"]
MARKER_1 = TEST_USERS["marker_headers"]
MARKER_2 = TEST_USERS["marker_headers_alt"]
MARKER_3 = TEST_USERS["marker_headers_third"]
APPEAL_OFFICER = TEST_USERS["appeal_officer_headers"]
APPEAL_OFFICER_2 = TEST_USERS["appeal_officer_headers_alt"]
TEST_HARNESS = TEST_USERS["test_harness_headers"]


# ===========================================================================
# Unique-id helpers
# ===========================================================================
def unique_candidate_id(prefix: str = "cand") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_title(prefix: str = "Exam") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ===========================================================================
# Clock helpers (PRD §2.5)
# ===========================================================================
def advance_clock(to_unix_seconds: int) -> Dict[str, Any]:
    """PRD §2.5: 'An admin-only test-driving capability advances that
    logical clock to a supplied to_unix_seconds instant.'"""
    return get_success_data(
        api_client.advance_clock(
            clock_advance_payload(to_unix_seconds), TEST_HARNESS,
        ),
    )


# ===========================================================================
# Tier 1: State Progression — Exam through OPEN_REGISTRATION / READY /
# IN_SESSION.
# ===========================================================================
def create_draft_exam(
    start_time: int = 1000,
    end_time: int = 2000,
    sampling_rule_type: str = "RANDOM",
    sampling_rule_spec: Optional[Dict[str, Any]] = None,
    appeal_window_seconds: int = 86400,
    option_shuffle: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Create an Exam in DRAFT. Defaults align with the deterministic
    clock origin so callers can advance the clock without surprises."""
    if sampling_rule_spec is None:
        sampling_rule_spec = {"target_count": 1}
    payload = create_exam_payload(
        title=unique_title(),
        start_time=start_time,
        end_time=end_time,
        sampling_rule_type=sampling_rule_type,
        sampling_rule_spec=sampling_rule_spec,
        appeal_window_seconds=appeal_window_seconds,
        option_shuffle=option_shuffle,
        **extra,
    )
    return get_success_data(api_client.create_exam(payload, EXAM_ADMIN))


def add_objective_question(
    exam_id: str,
    max_points: float = 10.0,
    correct_answer: Optional[List[str]] = None,
    difficulty: str = "EASY",
    topic: str = "general",
    question_type: str = "SINGLE_CHOICE",
    **extra: Any,
) -> Dict[str, Any]:
    payload = create_objective_question_payload(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
        max_points=max_points,
        correct_answer=correct_answer or ["B"],
        **extra,
    )
    return get_success_data(
        api_client.create_question(exam_id, payload, EXAM_ADMIN),
    )


def add_subjective_question(
    exam_id: str,
    max_points: float = 10.0,
    rubric: Optional[List[Dict[str, Any]]] = None,
    difficulty: str = "MEDIUM",
    topic: str = "general",
    question_type: str = "SHORT_ANSWER",
    **extra: Any,
) -> Dict[str, Any]:
    payload = create_subjective_question_payload(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
        max_points=max_points,
        rubric=rubric,
        **extra,
    )
    return get_success_data(
        api_client.create_question(exam_id, payload, EXAM_ADMIN),
    )


def open_registration(exam_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_registration(exam_id, EXAM_ADMIN),
    )


def close_registration(exam_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_registration(exam_id, EXAM_ADMIN),
    )


def register_candidate(
    exam_id: str,
    candidate_id: Optional[str] = None,
    id_card_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a CandidateRegistration. Returns the registration row;
    callers should retain ``candidate_id`` to pass into
    make_candidate_headers() for every subsequent Candidate-role call."""
    cid = candidate_id or unique_candidate_id()
    payload = create_registration_payload(
        candidate_id=cid,
        id_card_number=id_card_number or f"ID-{cid}",
    )
    reg = get_success_data(
        api_client.create_registration(exam_id, payload, EXAM_ADMIN),
    )
    # Echo the candidate_id back even if the server doesn't return it,
    # so callers always have it ready for header construction.
    reg.setdefault("candidate_id", cid)
    return reg


# ===========================================================================
# Tier 2: Exam in OPEN_REGISTRATION / READY / IN_SESSION with one
# registered candidate.
# ===========================================================================
def exam_ready_for_candidates(
    start_time: int = 1000,
    end_time: int = 2000,
    sampling_rule_type: str = "RANDOM",
    sampling_rule_spec: Optional[Dict[str, Any]] = None,
    num_objective: int = 1,
    num_subjective: int = 0,
    objective_max_points: float = 10.0,
    subjective_max_points: float = 10.0,
    option_shuffle: Optional[bool] = None,
    appeal_window_seconds: int = 86400,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Exam through OPEN_REGISTRATION with the requested question bank.
    Returns (exam, objective_questions, subjective_questions). The exam
    is NOT yet closed for registration — caller adds candidates first."""
    if sampling_rule_spec is None:
        # Default RANDOM target_count covers everything that will be added.
        total = num_objective + num_subjective
        sampling_rule_spec = {"target_count": max(1, total)}
    exam = create_draft_exam(
        start_time=start_time,
        end_time=end_time,
        sampling_rule_type=sampling_rule_type,
        sampling_rule_spec=sampling_rule_spec,
        appeal_window_seconds=appeal_window_seconds,
        option_shuffle=option_shuffle,
    )
    objective_qs: List[Dict[str, Any]] = []
    for _ in range(num_objective):
        objective_qs.append(
            add_objective_question(
                exam["id"], max_points=objective_max_points,
            ),
        )
    subjective_qs: List[Dict[str, Any]] = []
    for _ in range(num_subjective):
        subjective_qs.append(
            add_subjective_question(
                exam["id"], max_points=subjective_max_points,
            ),
        )
    open_registration(exam["id"])
    # Reflect the updated server-side status on the local exam dict so
    # downstream helpers (e.g. attempt_active / attempt_enrolled_only)
    # can detect the OPEN_REGISTRATION → READY transition they need.
    exam["status"] = "OPEN_REGISTRATION"
    return exam, objective_qs, subjective_qs


_USED_REG_IDS: set = set()


def _find_unused_registration(exam_id: str) -> Optional[Dict[str, Any]]:
    """Return a CandidateRegistration on this exam that hasn't yet been
    consumed by an attempt_active / attempt_enrolled_only / attempt_submitted
    call. The 'used' set is tracked at module level."""
    regs_resp = get_success_data(
        api_client.list_registrations(exam_id, EXAM_ADMIN, params={"limit": 100}),
    )
    regs = regs_resp if isinstance(regs_resp, list) else regs_resp.get("items", [])
    for r in regs:
        if r["id"] not in _USED_REG_IDS:
            return r
    return None


def pre_register_candidates(
    exam: Dict[str, Any], count: int,
) -> List[Dict[str, Any]]:
    """Register ``count`` fresh candidates while the exam is still in
    OPEN_REGISTRATION. The returned list can be threaded into subsequent
    attempt_active / attempt_submitted / attempt_enrolled_only calls
    (which also auto-pick from this pool when the exam has moved past
    OPEN_REGISTRATION). This is the standard pattern for tests that
    drive multiple candidates against a single exam."""
    regs: List[Dict[str, Any]] = []
    for _ in range(count):
        regs.append(register_candidate(exam["id"]))
    return regs


# ===========================================================================
# Tier 3: Walk a Candidate through ENROLLED → IDENTITY_PENDING → ACTIVE.
# ===========================================================================
def attempt_active(
    exam: Dict[str, Any],
    candidate_id: Optional[str] = None,
    pass_factors: bool = True,
    factors: Optional[Dict[str, bool]] = None,
    registration: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Drive one Candidate from registration through ACTIVE.

    Sequence:
      1. Register candidate (during OPEN_REGISTRATION) — skipped if a
         pre-built ``registration`` is supplied (multi-candidate setups
         that have to register every candidate before close).
      2. close-registration   → Exam READY.
      3. advance_clock to start_time → Exam IN_SESSION.
      4. POST attempts        → ExamAttempt ENROLLED.
      5. begin-identity-check → IDENTITY_PENDING.
      6. POST identity-verifications PRE_EXAM PASS → ACTIVE.

    Returns (registration, attempt, candidate_id). Each downstream call
    by this candidate MUST use make_candidate_headers(candidate_id).
    """
    if registration is not None:
        reg = registration
        cid = reg["candidate_id"]
    else:
        # If the exam is no longer in OPEN_REGISTRATION (because a prior
        # attempt_* helper already closed registration), auto-fall-back
        # to the most-recent unused registration we previously created
        # on this exam. Otherwise register a fresh one.
        cid = candidate_id or unique_candidate_id()
        current = get_success_data(
            api_client.get_exam(exam["id"], EXAM_ADMIN),
        )
        exam["status"] = current.get("status", exam.get("status"))
        if exam.get("status") == "OPEN_REGISTRATION":
            reg = register_candidate(exam["id"], candidate_id=cid)
        else:
            # Find an unused pre-registered candidate (one whose
            # candidate_id has no attempt yet) and use it.
            reg = _find_unused_registration(exam["id"])
            if reg is None:
                # Fall through to the (failing) register call so the
                # caller still sees a clear setup error from the server.
                reg = register_candidate(exam["id"], candidate_id=cid)
            else:
                cid = reg["candidate_id"]
    _USED_REG_IDS.add(reg["id"])
    # Close registration so the exam may transition to READY then
    # IN_SESSION as the clock advances. Refresh server-side status first
    # because the local dict may still say DRAFT/OPEN_REGISTRATION.
    current = get_success_data(
        api_client.get_exam(exam["id"], EXAM_ADMIN),
    )
    exam["status"] = current.get("status", exam.get("status"))
    if exam.get("status") == "OPEN_REGISTRATION":
        close_registration(exam["id"])
        exam["status"] = "READY"
    # Advance to start_time so Exam → IN_SESSION fires.
    advance_clock(exam["start_time"])
    # The attempt creation is ownership-gated (Candidate role).
    cand_headers = make_candidate_headers(cid)
    attempt = get_success_data(
        api_client.create_attempt(
            exam["id"], create_attempt_payload(reg["id"]), cand_headers,
        ),
    )
    # begin-identity-check
    attempt = get_success_data(
        api_client.begin_identity_check(
            exam["id"], attempt["id"], cand_headers,
        ),
    )
    # PRE_EXAM identity verification
    if factors is None:
        factors = {
            "id_card": True,
            "face": True,
            "live_detection": True,
        } if pass_factors else {
            "id_card": False, "face": True, "live_detection": True,
        }
    get_success_data(
        api_client.submit_identity_verification(
            exam["id"], attempt["id"],
            identity_verification_payload(
                verification_phase="PRE_EXAM",
                id_card=factors["id_card"],
                face=factors["face"],
                live_detection=factors["live_detection"],
            ),
            cand_headers,
        ),
    )
    # Refresh the attempt to capture ACTIVE state + composed paper.
    attempt = get_success_data(
        api_client.get_attempt(exam["id"], attempt["id"], cand_headers),
    )
    return reg, attempt, cid


def attempt_enrolled_only(
    exam: Dict[str, Any],
    candidate_id: Optional[str] = None,
    advance_to_in_session: bool = True,
    registration: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Drive a Candidate to ENROLLED without identity verification.
    Useful for tests that need an ENROLLED attempt (e.g., begin-identity-
    check while exam not yet IN_SESSION)."""
    if registration is not None:
        reg = registration
        cid = reg["candidate_id"]
    else:
        cid = candidate_id or unique_candidate_id()
        current = get_success_data(
            api_client.get_exam(exam["id"], EXAM_ADMIN),
        )
        exam["status"] = current.get("status", exam.get("status"))
        if exam.get("status") == "OPEN_REGISTRATION":
            reg = register_candidate(exam["id"], candidate_id=cid)
        else:
            reg = _find_unused_registration(exam["id"])
            if reg is None:
                reg = register_candidate(exam["id"], candidate_id=cid)
            else:
                cid = reg["candidate_id"]
    _USED_REG_IDS.add(reg["id"])
    current = get_success_data(
        api_client.get_exam(exam["id"], EXAM_ADMIN),
    )
    exam["status"] = current.get("status", exam.get("status"))
    if exam.get("status") == "OPEN_REGISTRATION":
        close_registration(exam["id"])
        exam["status"] = "READY"
    if advance_to_in_session:
        advance_clock(exam["start_time"])
    cand_headers = make_candidate_headers(cid)
    attempt = get_success_data(
        api_client.create_attempt(
            exam["id"], create_attempt_payload(reg["id"]), cand_headers,
        ),
    )
    return reg, attempt, cid


# ===========================================================================
# Tier 3b: Submitted attempt with subjective grading rows.
# ===========================================================================
def attempt_submitted(
    exam: Dict[str, Any],
    objective_questions: List[Dict[str, Any]],
    subjective_questions: List[Dict[str, Any]],
    candidate_id: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
    submit_at: Optional[int] = None,
    registration: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Drive a Candidate from registration through SUBMITTED. After
    submit, the server auto-grades objectives and creates BLIND_A /
    BLIND_B GradingAssignment rows for every subjective question (PRD
    §3.5)."""
    reg, attempt, cid = attempt_active(
        exam, candidate_id=candidate_id, registration=registration,
    )
    cand_headers = make_candidate_headers(cid)
    if submit_at is not None:
        advance_clock(submit_at)
    # Build default answers covering the paper. For objective questions,
    # answer with the correct option keys so the candidate scores full
    # marks (tests that need a wrong answer override via 'answers').
    if answers is None:
        answers = {}
        for q in objective_questions:
            if q["id"] in attempt.get("paper_question_ids", []):
                answers[q["id"]] = q.get("correct_answer", [])
        for q in subjective_questions:
            if q["id"] in attempt.get("paper_question_ids", []):
                answers[q["id"]] = "Candidate's free-form response."
    get_success_data(
        api_client.submit_attempt(
            exam["id"], attempt["id"],
            submit_attempt_payload(answers=answers),
            cand_headers,
        ),
    )
    attempt = get_success_data(
        api_client.get_attempt(exam["id"], attempt["id"], cand_headers),
    )
    return reg, attempt, cid


# ===========================================================================
# Tier 3c: Network suspend / resume helper.
# ===========================================================================
def cycle_suspend_resume(
    exam_id: str,
    attempt_id: str,
    candidate_id: str,
    suspend_at: int,
    resume_at: int,
) -> Dict[str, Any]:
    """Advance clock to suspend_at → POST network-disconnect → advance
    to resume_at → POST network-resume. Returns the latest attempt body."""
    cand_headers = make_candidate_headers(candidate_id)
    advance_clock(suspend_at)
    get_success_data(
        api_client.network_disconnect(exam_id, attempt_id, cand_headers),
    )
    advance_clock(resume_at)
    return get_success_data(
        api_client.network_resume(exam_id, attempt_id, cand_headers),
    )


# ===========================================================================
# Tier 3d: AbnormalEvent helper.
# ===========================================================================
def post_abnormal_event(
    exam_id: str,
    attempt_id: str,
    detected_at: int,
    behavior_rule_code: str = "MULTI_PERSON",
    monitoring_channel: str = "SCREEN",
    marking_mode: str = "REALTIME_ALERT",
    evidence_clip_uri: Optional[str] = "s3://evidence/clip.mp4",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Append an AbnormalEvent on the given attempt. Returns the event
    row."""
    return get_success_data(
        api_client.record_abnormal_event(
            exam_id, attempt_id,
            abnormal_event_payload(
                detected_at=detected_at,
                monitoring_channel=monitoring_channel,
                behavior_rule_code=behavior_rule_code,
                marking_mode=marking_mode,
                evidence_clip_uri=evidence_clip_uri,
            ),
            headers or PROCTOR,
        ),
    )


# ===========================================================================
# Tier 4: Subjective grading walk-through.
# ===========================================================================
def list_grading_rows_for_pair(
    exam_id: str,
    attempt_id: str,
    question_id: str,
) -> List[Dict[str, Any]]:
    """Return the GradingAssignment rows for (attempt_id, question_id)."""
    data = get_success_data(
        api_client.list_grading_assignments(
            exam_id, TEST_USERS["exam_admin_headers"],
            params={"limit": 100},
        ),
    )
    rows = data if isinstance(data, list) else data.get("items", [])
    return [
        r for r in rows
        if r.get("attempt_id") == attempt_id
        and r.get("question_id") == question_id
    ]


def resolve_subjective_question(
    exam_id: str,
    attempt_id: str,
    question_id: str,
    blind_a_points: float,
    blind_b_points: float,
    blind_a_marker_headers: Optional[Dict[str, str]] = None,
    blind_b_marker_headers: Optional[Dict[str, str]] = None,
    arbitration_points: Optional[float] = None,
    arbitration_marker_headers: Optional[Dict[str, str]] = None,
    rubric_breakdown_a: Optional[List[Dict[str, Any]]] = None,
    rubric_breakdown_b: Optional[List[Dict[str, Any]]] = None,
    rubric_breakdown_arb: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Two markers claim BLIND_A and BLIND_B and score them. If
    arbitration_points is supplied (caller anticipates |delta| > 2.0), a
    third marker claims the spawned ARBITRATION row.

    Returns the final GradingAssignment rows for this pair after resolution.
    """
    marker_a = blind_a_marker_headers or MARKER_1
    marker_b = blind_b_marker_headers or MARKER_2
    rows = list_grading_rows_for_pair(exam_id, attempt_id, question_id)
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    # Claim BLIND_A.
    get_success_data(
        api_client.claim_grading_assignment(
            exam_id, blind_a["id"], marker_a,
        ),
    )
    # Score BLIND_A.
    get_success_data(
        api_client.score_grading_assignment(
            exam_id, blind_a["id"],
            score_grading_payload(blind_a_points, rubric_breakdown_a),
            marker_a,
        ),
    )
    # Claim BLIND_B.
    get_success_data(
        api_client.claim_grading_assignment(
            exam_id, blind_b["id"], marker_b,
        ),
    )
    # Score BLIND_B.
    get_success_data(
        api_client.score_grading_assignment(
            exam_id, blind_b["id"],
            score_grading_payload(blind_b_points, rubric_breakdown_b),
            marker_b,
        ),
    )
    if arbitration_points is not None:
        # PRD §3.6: "if the gap strictly exceeds 2.0, a third
        # GradingAssignment row is spawned with blind_slot ARBITRATION".
        arb_rows = list_grading_rows_for_pair(
            exam_id, attempt_id, question_id,
        )
        arb_row = next(
            (r for r in arb_rows if r["blind_slot"] == "ARBITRATION"),
            None,
        )
        if arb_row is not None:
            arb_marker = arbitration_marker_headers or MARKER_3
            get_success_data(
                api_client.claim_grading_assignment(
                    exam_id, arb_row["id"], arb_marker,
                ),
            )
            get_success_data(
                api_client.score_grading_assignment(
                    exam_id, arb_row["id"],
                    score_grading_payload(
                        arbitration_points, rubric_breakdown_arb,
                    ),
                    arb_marker,
                ),
            )
    return list_grading_rows_for_pair(exam_id, attempt_id, question_id)


# ===========================================================================
# Tier 4b: Drive Exam through GRADING.
# ===========================================================================
def advance_to_grading(exam: Dict[str, Any]) -> Dict[str, Any]:
    """Advance the clock past Exam.end_time so the exam auto-transitions
    IN_SESSION → GRADING (and any still-ACTIVE/SUSPENDED attempts are
    forced to SUBMITTED)."""
    advance_clock(exam["end_time"])
    return get_success_data(
        api_client.get_exam(
            exam["id"], TEST_USERS["exam_admin_headers"],
        ),
    )


# ===========================================================================
# Tier 5: Drive Exam through SCORES_PUBLISHED → APPEAL_WINDOW. Set up
# one FINALIZED ExamAttempt ready to host appeals.
# ===========================================================================
def setup_finalized_exam_for_appeal(
    objective_max_points: float = 20.0,
    subjective_max_points: float = 10.0,
    blind_a_points: float = 8.0,
    blind_b_points: float = 7.0,
    objective_correct: bool = True,
    start_time: int = 1000,
    end_time: int = 2000,
    appeal_window_seconds: int = 86400,
) -> Dict[str, Any]:
    """Reach Exam in APPEAL_WINDOW with one FINALIZED attempt. Wires
    a single objective + single subjective question so callers can test
    appeals on either."""
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=start_time,
        end_time=end_time,
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 2},
        num_objective=1,
        num_subjective=1,
        objective_max_points=objective_max_points,
        subjective_max_points=subjective_max_points,
        appeal_window_seconds=appeal_window_seconds,
    )
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs,
        answers=None if objective_correct else {obj_qs[0]["id"]: ["A"]},
    )
    # Resolve the subjective question (BLIND_A=blind_a_points,
    # BLIND_B=blind_b_points; |delta| <= 2.0 ⇒ no arbitration).
    subj_q = subj_qs[0]
    resolve_subjective_question(
        exam["id"], attempt["id"], subj_q["id"],
        blind_a_points=blind_a_points,
        blind_b_points=blind_b_points,
    )
    # Force exam to GRADING (clock past end_time). After GRADING, the
    # attempt's GradingAssignment rows are all RESOLVED, so the attempt
    # auto-transitions SUBMITTED → GRADED.
    advance_clock(end_time)
    # Publish scores: GRADING → SCORES_PUBLISHED.
    exam = get_success_data(
        api_client.publish_scores(exam["id"], EXAM_ADMIN),
    )
    # One clock tick later → APPEAL_WINDOW.
    advance_clock(end_time + 1)
    exam = get_success_data(
        api_client.get_exam(
            exam["id"], TEST_USERS["exam_admin_headers"],
        ),
    )
    attempt = get_success_data(
        api_client.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ),
    )
    return {
        "exam": exam,
        "objective_question": obj_qs[0],
        "subjective_question": subj_qs[0],
        "registration": reg,
        "attempt": attempt,
        "candidate_id": cid,
        "blind_a_points": blind_a_points,
        "blind_b_points": blind_b_points,
    }


# ===========================================================================
# Tier 5b: Compose an exam in APPEAL_WINDOW with a SUBMITTED Appeal
# already on the books.
# ===========================================================================
def submit_appeal_for(
    exam_id: str,
    attempt_id: str,
    question_id: str,
    candidate_id: str,
    reason: str = "I believe my answer deserves more credit.",
) -> Dict[str, Any]:
    cand_headers = make_candidate_headers(candidate_id)
    return get_success_data(
        api_client.create_appeal(
            exam_id, attempt_id,
            create_appeal_payload(question_id, candidate_reason=reason),
            cand_headers,
        ),
    )


def drive_appeal_to_decision(
    exam_id: str,
    appeal_id: str,
    secondary_awarded_points: float,
    decision: str,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Claim → secondary-mark → decide."""
    officer = officer_headers or APPEAL_OFFICER
    get_success_data(
        api_client.claim_appeal(exam_id, appeal_id, officer),
    )
    get_success_data(
        api_client.secondary_mark_appeal(
            exam_id, appeal_id,
            secondary_mark_payload(secondary_awarded_points),
            officer,
        ),
    )
    return get_success_data(
        api_client.decide_appeal(
            exam_id, appeal_id,
            decide_appeal_payload(decision),
            officer,
        ),
    )


# ===========================================================================
# Convenience: a minimal "one objective question only" exam in IN_SESSION
# with one ACTIVE attempt. The simplest setup for tests that only need
# an ACTIVE attempt.
# ===========================================================================
def minimal_active_attempt(
    start_time: int = 1000,
    end_time: int = 2000,
) -> Dict[str, Any]:
    """Returns a dict with exam, attempt, registration, candidate_id."""
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=start_time,
        end_time=end_time,
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 1},
        num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    return {
        "exam": exam,
        "objective_question": obj_qs[0],
        "registration": reg,
        "attempt": attempt,
        "candidate_id": cid,
    }


__all__ = [
    "EXAM_ADMIN",
    "PROCTOR",
    "MARKER_1",
    "MARKER_2",
    "MARKER_3",
    "APPEAL_OFFICER",
    "APPEAL_OFFICER_2",
    "TEST_HARNESS",
    "unique_candidate_id",
    "unique_title",
    "advance_clock",
    "create_draft_exam",
    "add_objective_question",
    "add_subjective_question",
    "open_registration",
    "close_registration",
    "register_candidate",
    "pre_register_candidates",
    "exam_ready_for_candidates",
    "attempt_active",
    "attempt_enrolled_only",
    "attempt_submitted",
    "cycle_suspend_resume",
    "post_abnormal_event",
    "list_grading_rows_for_pair",
    "resolve_subjective_question",
    "advance_to_grading",
    "setup_finalized_exam_for_appeal",
    "submit_appeal_for",
    "drive_appeal_to_decision",
    "minimal_active_attempt",
]
