"""Question bank endpoints under /exams/{examId}/questions."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list


bp = Blueprint("questions", __name__)


VALID_QTYPES = {"SINGLE_CHOICE", "MULTI_CHOICE", "TRUE_FALSE",
                "SHORT_ANSWER", "ESSAY"}
OBJECTIVE = {"SINGLE_CHOICE", "MULTI_CHOICE", "TRUE_FALSE"}
SUBJECTIVE = {"SHORT_ANSWER", "ESSAY"}
VALID_DIFF = {"EASY", "MEDIUM", "HARD"}


def _question_view(q: dict) -> dict:
    return db.public(q)


@bp.post("/exams/<exam_id>/questions")
@require_auth(roles={"ExamAdmin"})
def add_question(exam_id):
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    body = get_json_body()
    qtype = body.get("question_type")
    difficulty = body.get("difficulty")
    topic = body.get("topic")
    stem = body.get("stem")
    options = body.get("options")
    correct = body.get("correct_answer")
    max_points = body.get("max_points")
    rubric = body.get("rubric")

    if qtype not in VALID_QTYPES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid question_type {qtype!r}")
    if difficulty not in VALID_DIFF:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid difficulty {difficulty!r}")
    if not isinstance(topic, str):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "topic must be a string")
    if not isinstance(stem, str):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "stem must be a string")
    if max_points is None or isinstance(max_points, bool):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "max_points required")
    try:
        max_pts_dec = Decimal(str(max_points))
    except Exception:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "max_points must be a number")
    if max_pts_dec <= 0:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "max_points must be > 0")

    # Rubric validation (priority 11)
    if qtype in OBJECTIVE:
        # Objective MUST NOT carry a rubric.
        if rubric is not None and rubric != []:
            raise err("ERR_RUBRIC_INVALID",
                      "objective questions must not carry a rubric")
    else:
        # Subjective MUST carry a rubric whose points sum to max_points.
        if not isinstance(rubric, list) or len(rubric) == 0:
            raise err("ERR_RUBRIC_INVALID",
                      "subjective questions require a rubric")
        rubric_sum = Decimal("0")
        for item in rubric:
            if not isinstance(item, dict) or "keypoint" not in item or "points" not in item:
                raise err("ERR_RUBRIC_INVALID",
                          "rubric items require keypoint and points")
            try:
                rubric_sum += Decimal(str(item["points"]))
            except Exception:
                raise err("ERR_RUBRIC_INVALID",
                          "rubric item points must be numeric")
        if rubric_sum != max_pts_dec:
            raise err("ERR_RUBRIC_INVALID",
                      "rubric points must sum to max_points")

    # Options validation
    if qtype in ("SINGLE_CHOICE", "MULTI_CHOICE"):
        if not isinstance(options, list) or not options:
            raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                      "options required for choice questions")
        for o in options:
            if not isinstance(o, dict) or "option_key" not in o or "text" not in o:
                raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                          "each option must carry option_key and text")

    # correct_answer must be a list per scaffold.
    if not isinstance(correct, list):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "correct_answer must be an array")

    q = {
        "exam_id": exam_id,
        "question_type": qtype,
        "difficulty": difficulty,
        "topic": topic,
        "stem": stem,
        "options": options if qtype in ("SINGLE_CHOICE", "MULTI_CHOICE") else [],
        "correct_answer": correct,
        "max_points": float(max_pts_dec),
        "rubric": rubric if qtype in SUBJECTIVE else None,
    }
    db.stamp_create(q, common_fields=True)
    db.questions[q["id"]] = q
    return success(_question_view(q), 201)


@bp.get("/exams/<exam_id>/questions")
@require_auth(roles={"ExamAdmin", "Proctor"})
def list_questions(exam_id):
    if exam_id not in db.exams:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    limit, offset = get_pagination()
    rows = sorted(
        [q for q in db.questions.values() if q.get("exam_id") == exam_id],
        key=lambda q: q["_seq"],
    )
    total = len(rows)
    page = [_question_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.get("/exams/<exam_id>/questions/<question_id>")
@require_auth(roles={"ExamAdmin", "Proctor"})
def get_question(exam_id, question_id):
    if exam_id not in db.exams:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    q = db.questions.get(question_id)
    if q is None or q.get("exam_id") != exam_id:
        raise err("ERR_QUESTION_NOT_FOUND", "question not found")
    return success(_question_view(q))
