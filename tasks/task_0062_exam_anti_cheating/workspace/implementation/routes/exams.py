"""Exam CRUD + lifecycle: create/list/get + open/close registration + publish."""
from flask import Blueprint, g

import db
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list
from services.util import occ_check
from services import paper, scoring, clock_tick
from services.audit import append_audit
from clock import now_unix


bp = Blueprint("exams", __name__)


VALID_SAMPLING_TYPES = {"RANDOM", "STRATIFIED", "BLUEPRINT"}


def _exam_view(e: dict) -> dict:
    # PRD §3.1: a newly created exam starts with grading_progress_pct
    # at 0; PRD §3.6 then says "When total_slots is zero the percentage
    # is reported as 100" — that 100 reading applies once the exam has
    # progressed past the initial DRAFT state where the §3.1 anchor
    # value owns the field.
    if e.get("status") != "DRAFT":
        e["grading_progress_pct"] = scoring.recompute_grading_progress(e["id"])
    return db.public(e)


@bp.post("/exams")
@require_auth(roles={"ExamAdmin"})
def create_exam():
    body = get_json_body()
    title = body.get("title")
    start_time = body.get("start_time")
    end_time = body.get("end_time")
    rule_type = body.get("sampling_rule_type")
    rule_spec = body.get("sampling_rule_spec")

    if not isinstance(title, str) or not title:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "title required")
    if not isinstance(start_time, int) or isinstance(start_time, bool):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "start_time must be integer unix seconds")
    if not isinstance(end_time, int) or isinstance(end_time, bool):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "end_time must be integer unix seconds")
    if rule_type not in VALID_SAMPLING_TYPES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid sampling_rule_type {rule_type!r}")
    if not isinstance(rule_spec, dict):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "sampling_rule_spec required and must be an object")

    exam = {
        "title": title,
        "start_time": int(start_time),
        "end_time": int(end_time),
        "appeal_window_seconds": int(body.get("appeal_window_seconds", 86400)),
        "per_question_time_limit_seconds": int(body.get("per_question_time_limit_seconds", 0)),
        "sampling_rule_type": rule_type,
        "sampling_rule_spec": rule_spec,
        "option_shuffle": bool(body.get("option_shuffle", True)),
        "max_score": 0,
        "grading_progress_pct": 0,
        "status": "DRAFT",
    }
    db.stamp_create(exam, common_fields=True)
    db.exams[exam["id"]] = exam
    return success(_exam_view(exam), 201)


@bp.get("/exams")
@require_auth()  # Any authenticated role
def list_exams():
    limit, offset = get_pagination()
    rows = sorted(db.exams.values(), key=lambda e: e["_seq"])
    total = len(rows)
    page = [_exam_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.get("/exams/<exam_id>")
@require_auth()
def get_exam(exam_id):
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    return success(_exam_view(exam))


@bp.post("/exams/<exam_id>/open-registration")
@require_auth(roles={"ExamAdmin"})
def open_registration(exam_id):
    body = get_json_body()
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    if exam.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"open-registration requires DRAFT (got {exam.get('status')})")
    occ_check(exam, body)
    # Business constraints (priority 10)
    bank = [q for q in db.questions.values() if q.get("exam_id") == exam_id]
    if not bank:
        raise err("ERR_QUESTION_BANK_EMPTY", "no questions in bank")
    paper.check_sampling_feasibility(exam)

    # max_score recomputed
    total = 0
    from decimal import Decimal
    acc = Decimal("0")
    for q in bank:
        acc += Decimal(str(q.get("max_points", 0)))
    exam["max_score"] = float(acc)
    exam["status"] = "OPEN_REGISTRATION"
    db.stamp_update(exam)
    return success(_exam_view(exam))


@bp.post("/exams/<exam_id>/close-registration")
@require_auth(roles={"ExamAdmin"})
def close_registration(exam_id):
    body = get_json_body()
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    if exam.get("status") != "OPEN_REGISTRATION":
        raise err("ERR_INVALID_STATE",
                  f"close-registration requires OPEN_REGISTRATION (got {exam.get('status')})")
    occ_check(exam, body)
    exam["status"] = "READY"
    db.stamp_update(exam)
    return success(_exam_view(exam))


@bp.post("/exams/<exam_id>/publish-scores")
@require_auth(roles={"ExamAdmin"})
def publish_scores(exam_id):
    body = get_json_body()
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    if exam.get("status") != "GRADING":
        raise err("ERR_EXAM_NOT_GRADING",
                  f"publish-scores requires GRADING (got {exam.get('status')})")
    occ_check(exam, body)
    # Make sure progress is fresh.
    exam["grading_progress_pct"] = scoring.recompute_grading_progress(exam_id)
    if float(exam["grading_progress_pct"]) < 100:
        raise err("ERR_GRADING_INCOMPLETE", "grading_progress_pct < 100")

    # Freeze final_score on every non-DISQUALIFIED attempt; status → FINALIZED.
    for att in db.attempts.values():
        if att.get("exam_id") != exam_id:
            continue
        if att.get("status") == "DISQUALIFIED":
            continue
        # If still in SUBMITTED somehow (e.g., no subjective), finalise.
        if att.get("status") == "SUBMITTED":
            scoring.maybe_finalize_attempt(att)
        if att.get("status") == "GRADED":
            att["status"] = "FINALIZED"
            db.stamp_update(att)

    exam["status"] = "SCORES_PUBLISHED"
    exam["_published_at_unix"] = now_unix()
    db.stamp_update(exam)
    return success(_exam_view(exam))
