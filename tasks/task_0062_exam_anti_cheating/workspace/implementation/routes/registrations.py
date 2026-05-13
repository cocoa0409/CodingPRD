"""CandidateRegistration endpoints."""
from flask import Blueprint

import db
from clock import now_unix
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list


bp = Blueprint("registrations", __name__)


def _view(r: dict) -> dict:
    return db.public(r)


@bp.post("/exams/<exam_id>/registrations")
@require_auth(roles={"ExamAdmin"})
def register_candidate(exam_id):
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    if exam.get("status") != "OPEN_REGISTRATION":
        raise err("ERR_INVALID_STATE",
                  "registration only during OPEN_REGISTRATION")
    body = get_json_body()
    candidate_id = body.get("candidate_id")
    id_card_number = body.get("id_card_number")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "candidate_id required")
    if not isinstance(id_card_number, str) or not id_card_number:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "id_card_number required")
    reg = {
        "exam_id": exam_id,
        "candidate_id": candidate_id,
        "id_card_number": id_card_number,
        "enrolled_at": now_unix(),
        "status": "REGISTERED",
    }
    db.stamp_create(reg, common_fields=True)
    db.registrations[reg["id"]] = reg
    return success(_view(reg), 201)


@bp.get("/exams/<exam_id>/registrations")
@require_auth(roles={"ExamAdmin"})
def list_registrations(exam_id):
    if exam_id not in db.exams:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    limit, offset = get_pagination()
    rows = sorted(
        [r for r in db.registrations.values() if r.get("exam_id") == exam_id],
        key=lambda r: r["_seq"],
    )
    total = len(rows)
    page = [_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)
