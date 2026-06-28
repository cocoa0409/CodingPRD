"""Worksheet endpoints and grading cycle (PRD §3.4)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from services import advancement

bp = Blueprint("worksheets", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}


def _parent_owns_worksheet(uid, w):
    enr = db.enrollments.get(w["enrollment_id"])
    if not enr:
        return False
    return helpers.parent_owns_family(uid, helpers.family_id_of_student(enr["student_id"]))


@bp.route("/worksheets", methods=["POST"])
def create_worksheet():
    _uid, role = get_auth()
    require_role(role, {"CenterDirector", "Instructor"})
    body = get_body()

    enrollment_id = helpers.require_str(body, "enrollment_id")
    level_id = helpers.require_str(body, "level_id")
    set_number = helpers.require_int(body, "set_number", minimum=1)

    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    level = db.levels.get(level_id)
    if not level:
        raise errors.not_found()

    # Level/subject coherence (priority 11): level must belong to enrollment's subject.
    if level["subject_id"] != enr["subject_id"]:
        raise errors.level_subject_mismatch()

    obj = {
        "enrollment_id": enrollment_id,
        "level_id": level_id,
        "set_number": set_number,
        "score": None,
        "attempt_count": 0,
        "status": "ASSIGNED",
    }
    db.stamp_create(obj)
    db.worksheets[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/worksheets/<worksheet_id>", methods=["GET"])
def get_worksheet(worksheet_id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    w = db.worksheets.get(worksheet_id)
    if not w:
        raise errors.not_found()
    if role == "Parent" and not _parent_owns_worksheet(uid, w):
        raise errors.forbidden()
    return success(public(w))


@bp.route("/worksheets", methods=["GET"])
def list_worksheets():
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    args = request.args
    items = list(db.worksheets.values())
    for key in ("enrollment_id", "level_id", "status"):
        val = args.get(key)
        if val:
            items = [w for w in items if w.get(key) == val]
    if role == "Parent":
        items = [w for w in items if _parent_owns_worksheet(uid, w)]
    return helpers.paginate_and_respond(items)


@bp.route("/worksheets/<worksheet_id>/grade", methods=["POST"])
def grade_worksheet(worksheet_id):
    _uid, role = get_auth()
    require_role(role, {"Instructor"})
    w = db.worksheets.get(worksheet_id)
    if not w:
        raise errors.not_found()
    body = get_body()

    # well-formedness (priority 4): score present & 0..100 (ERR_SCORE_OUT_OF_RANGE).
    if "score" not in body or body["score"] is None:
        raise errors.invalid_request("Missing required field: score.")
    score = body["score"]
    if isinstance(score, bool) or not isinstance(score, int):
        raise errors.invalid_request("score must be an integer.")
    if score < 0 or score > 100:
        raise errors.score_out_of_range()

    # state guard (priority 6): worksheet must be ASSIGNED.
    if w["status"] != "ASSIGNED":
        raise errors.invalid_state()

    # cross-entity: parent enrollment must be ACTIVE.
    enr = db.enrollments.get(w["enrollment_id"])
    if not enr or enr["status"] != "ACTIVE":
        raise errors.enrollment_not_active()

    # grade
    w["score"] = score
    w["attempt_count"] += 1
    w["status"] = "GRADED"
    db.touch(w)

    # immediate resolution: MASTERED (>= threshold) or RETRY (< threshold)
    level = db.levels.get(w["level_id"])
    threshold = level["mastery_score_threshold"] if level else 0
    if score >= threshold:
        w["status"] = "MASTERED"
        db.touch(w)
        advancement.run_advancement(enr)
    else:
        w["status"] = "RETRY"
        db.touch(w)

    return success(public(w))


@bp.route("/worksheets/<worksheet_id>/reassign", methods=["POST"])
def reassign_worksheet(worksheet_id):
    _uid, role = get_auth()
    require_role(role, {"Instructor"})
    w = db.worksheets.get(worksheet_id)
    if not w:
        raise errors.not_found()

    if w["status"] != "RETRY":
        raise errors.invalid_state()

    enr = db.enrollments.get(w["enrollment_id"])
    if not enr or enr["status"] != "ACTIVE":
        raise errors.enrollment_not_active()

    w["status"] = "ASSIGNED"
    w["score"] = None
    db.touch(w)
    return success(public(w))
