"""GradingAssignment endpoints: list / claim / score."""
from decimal import Decimal

from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_auth, get_json_body, get_pagination
from response import success, success_list
from services import grading
from services.util import occ_check


bp = Blueprint("grading_assignments", __name__)


def _view(r: dict) -> dict:
    return db.public(r)


def _require_exam(exam_id):
    if exam_id not in db.exams:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")


def _require_assignment(exam_id, assignment_id) -> dict:
    _require_exam(exam_id)
    r = db.grading_assignments.get(assignment_id)
    if r is None:
        raise err("ERR_GRADING_ASSIGNMENT_NOT_FOUND", "grading-assignment not found")
    # nested ownership: ensure the row belongs to this exam.
    attempt = db.attempts.get(r.get("attempt_id"))
    if attempt is None or attempt.get("exam_id") != exam_id:
        raise err("ERR_GRADING_ASSIGNMENT_NOT_FOUND", "grading-assignment not found")
    return r


@bp.get("/exams/<exam_id>/grading-assignments")
@require_auth(roles={"Marker", "ExamAdmin"})
def list_assignments(exam_id):
    _require_exam(exam_id)
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    rows = []
    for r in db.grading_assignments.values():
        attempt = db.attempts.get(r.get("attempt_id"))
        if attempt is None or attempt.get("exam_id") != exam_id:
            continue
        if status_filter and r.get("status") != status_filter:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = [_view(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.post("/exams/<exam_id>/grading-assignments/<assignment_id>/claim")
@require_auth(roles={"Marker"})
def claim_assignment(exam_id, assignment_id):
    row = _require_assignment(exam_id, assignment_id)
    body = get_json_body()
    if row.get("status") != "PENDING":
        # Race: another marker already claimed.
        if row.get("status") == "IN_PROGRESS":
            raise err("ERR_GRADING_ALREADY_CLAIMED", "assignment already claimed")
        raise err("ERR_INVALID_STATE",
                  f"claim requires PENDING (got {row.get('status')})")
    occ_check(row, body)
    # Double-blind invariant
    if grading.double_blind_conflict(row["attempt_id"], row["question_id"], g.user_id):
        raise err("ERR_DOUBLE_BLIND_VIOLATION",
                  "marker previously scored sibling slot")
    row["marker_id"] = g.user_id
    row["status"] = "IN_PROGRESS"
    db.stamp_update(row)
    return success(_view(row))


@bp.post("/exams/<exam_id>/grading-assignments/<assignment_id>/score")
@require_auth(roles={"Marker"})
def score_assignment(exam_id, assignment_id):
    row = _require_assignment(exam_id, assignment_id)
    body = get_json_body()

    if row.get("status") != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE",
                  f"score requires IN_PROGRESS (got {row.get('status')})")
    # Marker identity must match the claimer (otherwise insufficient permissions).
    if row.get("marker_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "only the claiming marker may score this assignment")
    occ_check(row, body)

    awarded = body.get("awarded_points")
    rubric = body.get("rubric_breakdown")

    question = db.questions.get(row.get("question_id"))
    if question is None:
        raise err("ERR_QUESTION_NOT_FOUND", "question not found")
    max_pts = Decimal(str(question.get("max_points", 0)))

    if awarded is None or isinstance(awarded, bool):
        raise err("ERR_AWARDED_OUT_OF_RANGE", "awarded_points required")
    try:
        awarded_dec = Decimal(str(awarded))
    except Exception:
        raise err("ERR_AWARDED_OUT_OF_RANGE", "awarded_points must be numeric")
    if awarded_dec < 0 or awarded_dec > max_pts:
        raise err("ERR_AWARDED_OUT_OF_RANGE",
                  "awarded_points outside [0, max_points]")

    if not isinstance(rubric, list):
        raise err("ERR_RUBRIC_SUM_MISMATCH", "rubric_breakdown required")
    rubric_sum = Decimal("0")
    for item in rubric:
        if not isinstance(item, dict) or "points" not in item:
            raise err("ERR_RUBRIC_SUM_MISMATCH",
                      "each rubric_breakdown item requires points")
        try:
            rubric_sum += Decimal(str(item["points"]))
        except Exception:
            raise err("ERR_RUBRIC_SUM_MISMATCH", "rubric points must be numeric")
    if rubric_sum != awarded_dec:
        raise err("ERR_RUBRIC_SUM_MISMATCH",
                  "rubric_breakdown points must sum to awarded_points")

    row["awarded_points"] = float(awarded_dec)
    row["rubric_breakdown"] = rubric
    row["status"] = "SUBMITTED"
    db.stamp_update(row)

    # Resolve sibling pair / spawn arbitration as needed.
    grading.resolve_pair_if_ready(row)
    # Recompute provisional/final and grading_progress.
    grading.post_score_recompute(row)
    return success(_view(row))
