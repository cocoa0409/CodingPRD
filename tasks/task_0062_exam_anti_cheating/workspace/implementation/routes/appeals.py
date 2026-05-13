"""Appeal endpoints: submit / claim / secondary-mark / decide / list."""
from decimal import Decimal

from flask import Blueprint, g

import db
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list
from services.util import occ_check, round_half_up_2dp
from services.audit import append_audit
from services import scoring


bp = Blueprint("appeals", __name__)


def _view(r: dict) -> dict:
    return db.public(r)


def _require_exam(exam_id):
    e = db.exams.get(exam_id)
    if e is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    return e


def _require_attempt(exam_id, attempt_id):
    _require_exam(exam_id)
    a = db.attempts.get(attempt_id)
    if a is None or a.get("exam_id") != exam_id:
        raise err("ERR_ATTEMPT_NOT_FOUND", "attempt not found")
    return a


def _require_appeal(exam_id, appeal_id):
    _require_exam(exam_id)
    a = db.appeals.get(appeal_id)
    if a is None:
        raise err("ERR_APPEAL_NOT_FOUND", "appeal not found")
    attempt = db.attempts.get(a.get("attempt_id"))
    if attempt is None or attempt.get("exam_id") != exam_id:
        raise err("ERR_APPEAL_NOT_FOUND", "appeal not found")
    return a


def _prior_per_question_subjective(attempt: dict, question_id: str) -> float:
    """Compute the per-question subjective value used in the most recent
    final_score_calculation for the given question (the value that
    score_delta is computed against per PRD §3.7).

    If an earlier APPROVED appeal for the same (attempt, question) has
    already adjusted the per-question value, the *most recent* such
    appeal's secondary_awarded_points is what counts as 'prior' (it
    overrode the resolved-row mean). Otherwise the value is the
    arbitration award or the blind-A/B rounded mean.
    """
    # 1. Check for prior APPROVED appeals on the same (attempt, question).
    prior_appeals = [
        ap for ap in db.appeals.values()
        if ap.get("attempt_id") == attempt["id"]
        and ap.get("question_id") == question_id
        and ap.get("status") == "APPROVED"
    ]
    if prior_appeals:
        prior_appeals.sort(key=lambda r: r["_seq"])
        latest = prior_appeals[-1]
        return round_half_up_2dp(
            Decimal(str(latest.get("secondary_awarded_points", 0))),
        )
    # 2. Otherwise fall back to the resolved-row computation.
    rows = [
        r for r in db.grading_assignments.values()
        if r.get("attempt_id") == attempt["id"]
        and r.get("question_id") == question_id
        and r.get("status") == "RESOLVED"
    ]
    if not rows:
        return 0.0
    arb = next((r for r in rows if r.get("blind_slot") == "ARBITRATION"), None)
    if arb is not None:
        return round_half_up_2dp(arb.get("awarded_points", 0))
    a = next((r for r in rows if r.get("blind_slot") == "BLIND_A"), None)
    b = next((r for r in rows if r.get("blind_slot") == "BLIND_B"), None)
    if a is None or b is None:
        return 0.0
    mean = (Decimal(str(a.get("awarded_points", 0)))
            + Decimal(str(b.get("awarded_points", 0)))) / Decimal("2")
    return round_half_up_2dp(mean)


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/appeals")
@require_auth(roles={"Candidate"})
def submit_appeal(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    attempt = _require_attempt(exam_id, attempt_id)
    # Candidate ownership
    reg = db.registrations.get(attempt.get("registration_id"))
    if reg is None or reg.get("candidate_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your attempt")
    body = get_json_body()
    question_id = body.get("question_id")
    reason = body.get("candidate_reason")
    if not isinstance(question_id, str) or not question_id:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "question_id required")
    if not isinstance(reason, str):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "candidate_reason required")

    # exam state precondition (priority 4)
    if exam.get("status") != "APPEAL_WINDOW":
        raise err("ERR_EXAM_NOT_IN_APPEAL_WINDOW",
                  f"appeals require APPEAL_WINDOW (got {exam.get('status')})")
    # business referential: question must be on the candidate's paper.
    if question_id not in (attempt.get("paper_question_ids") or []):
        raise err("ERR_QUESTION_NOT_ON_PAPER",
                  "question_id not on candidate's paper")

    appeal = {
        "attempt_id": attempt_id,
        "question_id": question_id,
        "candidate_reason": reason,
        "secondary_awarded_points": None,
        "decision": None,
        "score_delta": None,
        "status": "SUBMITTED",
    }
    db.stamp_create(appeal, common_fields=True)
    db.appeals[appeal["id"]] = appeal
    return success(_view(appeal), 201)


@bp.post("/exams/<exam_id>/appeals/<appeal_id>/claim")
@require_auth(roles={"AppealOfficer"})
def claim_appeal(exam_id, appeal_id):
    exam = _require_exam(exam_id)
    appeal = _require_appeal(exam_id, appeal_id)
    body = get_json_body()
    # State precondition (priority 5)
    if appeal.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  f"claim requires SUBMITTED (got {appeal.get('status')})")
    # Exam state (priority 4): only during APPEAL_WINDOW
    if exam.get("status") != "APPEAL_WINDOW":
        raise err("ERR_EXAM_NOT_IN_APPEAL_WINDOW",
                  f"appeal claim requires APPEAL_WINDOW (got {exam.get('status')})")
    occ_check(appeal, body)
    # SOD: officer must not be a prior marker on the same (attempt, question).
    for r in db.grading_assignments.values():
        if (r.get("attempt_id") == appeal["attempt_id"]
                and r.get("question_id") == appeal["question_id"]
                and r.get("marker_id") == g.user_id):
            raise err("ERR_APPEAL_OFFICER_WAS_MARKER",
                      "appeal officer previously marked this question")
    appeal["status"] = "UNDER_REVIEW"
    db.stamp_update(appeal)
    return success(_view(appeal))


@bp.post("/exams/<exam_id>/appeals/<appeal_id>/secondary-mark")
@require_auth(roles={"AppealOfficer"})
def secondary_mark(exam_id, appeal_id):
    exam = _require_exam(exam_id)
    appeal = _require_appeal(exam_id, appeal_id)
    body = get_json_body()
    if appeal.get("status") != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"secondary-mark requires UNDER_REVIEW (got {appeal.get('status')})")
    occ_check(appeal, body)
    pts = body.get("secondary_awarded_points")
    if pts is None or isinstance(pts, bool):
        raise err("ERR_AWARDED_OUT_OF_RANGE",
                  "secondary_awarded_points required")
    try:
        pts_dec = Decimal(str(pts))
    except Exception:
        raise err("ERR_AWARDED_OUT_OF_RANGE",
                  "secondary_awarded_points must be numeric")
    question = db.questions.get(appeal["question_id"])
    if question is None:
        raise err("ERR_QUESTION_NOT_FOUND", "question not found")
    max_pts = Decimal(str(question.get("max_points", 0)))
    if pts_dec < 0 or pts_dec > max_pts:
        raise err("ERR_AWARDED_OUT_OF_RANGE",
                  "secondary_awarded_points outside [0, max_points]")
    attempt = db.attempts.get(appeal["attempt_id"])
    prior = _prior_per_question_subjective(attempt, appeal["question_id"])
    delta = float(pts_dec - Decimal(str(prior)))
    appeal["secondary_awarded_points"] = float(pts_dec)
    appeal["score_delta"] = delta
    appeal["status"] = "DECISION_PENDING"
    db.stamp_update(appeal)
    return success(_view(appeal))


@bp.post("/exams/<exam_id>/appeals/<appeal_id>/decide")
@require_auth(roles={"AppealOfficer"})
def decide_appeal(exam_id, appeal_id):
    exam = _require_exam(exam_id)
    appeal = _require_appeal(exam_id, appeal_id)
    body = get_json_body()
    if appeal.get("status") != "DECISION_PENDING":
        raise err("ERR_INVALID_STATE",
                  f"decide requires DECISION_PENDING (got {appeal.get('status')})")
    occ_check(appeal, body)
    decision = body.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "decision must be APPROVED or REJECTED")
    appeal["decision"] = decision
    appeal["status"] = decision
    db.stamp_update(appeal)

    if decision == "APPROVED":
        attempt = db.attempts.get(appeal["attempt_id"])
        if attempt is not None:
            prior_final = attempt.get("final_score")
            delta = float(appeal.get("score_delta") or 0)
            # The disqualification override still wins: if attempt is
            # DISQUALIFIED, final_score stays 0.
            if attempt.get("status") != "DISQUALIFIED":
                attempt["_appeals_delta"] = float(
                    Decimal(str(attempt.get("_appeals_delta", 0.0)))
                    + Decimal(str(delta))
                )
                scoring.recompute_attempt_scores(attempt)
                db.stamp_update(attempt)
            append_audit(
                subject_type="APPEAL",
                subject_id=appeal["id"],
                actor_role="AppealOfficer",
                actor_id=g.user_id,
                action_code="APPEAL_APPROVED",
                delta={
                    "before": {"final_score": prior_final},
                    "after": {"final_score": attempt.get("final_score")},
                },
            )
            # Also emit a SCORE_ADJUSTED audit row keyed on the attempt
            # whose score was actually adjusted (PRD §2.9's "subject_id
            # of the affected instance"; the affected instance for the
            # score change is the attempt, not the appeal).
            append_audit(
                subject_type="SCORE_ADJUSTMENT",
                subject_id=attempt["id"],
                actor_role="AppealOfficer",
                actor_id=g.user_id,
                action_code="SCORE_ADJUSTED",
                delta={
                    "before": {"final_score": prior_final},
                    "after": {"final_score": attempt.get("final_score")},
                },
            )
    else:
        # REJECTED: audit row for traceability, no score adjustment.
        append_audit(
            subject_type="APPEAL",
            subject_id=appeal["id"],
            actor_role="AppealOfficer",
            actor_id=g.user_id,
            action_code="APPEAL_APPROVED",  # action_code enum from scaffold; rejection captured in delta
            delta={
                "before": {"status": "DECISION_PENDING"},
                "after": {"status": "REJECTED"},
            },
        )

    return success(_view(appeal))


@bp.get("/exams/<exam_id>/appeals")
@require_auth(roles={"Candidate", "AppealOfficer", "ExamAdmin"})
def list_appeals(exam_id):
    _require_exam(exam_id)
    limit, offset = get_pagination()
    role = g.user_role
    rows = []
    for ap in db.appeals.values():
        attempt = db.attempts.get(ap.get("attempt_id"))
        if attempt is None or attempt.get("exam_id") != exam_id:
            continue
        if role == "Candidate":
            reg = db.registrations.get(attempt.get("registration_id"))
            if reg is None or reg.get("candidate_id") != g.user_id:
                continue
        elif role == "AppealOfficer":
            if ap.get("status") not in ("SUBMITTED", "UNDER_REVIEW"):
                continue
        rows.append(ap)
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = [_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)
