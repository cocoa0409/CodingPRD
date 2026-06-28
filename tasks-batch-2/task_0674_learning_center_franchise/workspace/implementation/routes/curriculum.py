"""Subject and CurriculumLevel endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success

bp = Blueprint("curriculum", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}


# =========================================================================
# Subject
# =========================================================================
@bp.route("/subjects", methods=["POST"])
def create_subject():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    body = get_body()

    center_id = helpers.require_str(body, "center_id")
    name = helpers.require_str(body, "name")
    code = helpers.require_str(body, "code")

    if center_id not in db.centers:
        raise errors.not_found()

    # code unique within a center.
    for s in db.subjects.values():
        if s["center_id"] == center_id and s["code"] == code:
            raise errors.invalid_request("Subject code must be unique within a center.")

    obj = {
        "center_id": center_id,
        "name": name,
        "code": code,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    db.subjects[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/subjects/<subject_id>", methods=["GET"])
def get_subject(subject_id):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    subject = db.subjects.get(subject_id)
    if not subject:
        raise errors.not_found()
    return success(public(subject))


@bp.route("/subjects", methods=["GET"])
def list_subjects():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    center_id = request.args.get("center_id")
    items = list(db.subjects.values())
    if center_id:
        items = [s for s in items if s["center_id"] == center_id]
    return helpers.paginate_and_respond(items)


# =========================================================================
# CurriculumLevel
# =========================================================================
@bp.route("/curriculum-levels", methods=["POST"])
def create_level():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    body = get_body()

    subject_id = helpers.require_str(body, "subject_id")
    rank = helpers.require_int(body, "rank", minimum=1)
    label = helpers.require_str(body, "label")
    prereq_level_id = body.get("prereq_level_id")
    worksheets_to_master = helpers.require_int(body, "worksheets_to_master", minimum=1, default=10, required=False)
    mastery_threshold = helpers.require_int(body, "mastery_score_threshold", minimum=0, maximum=100, default=80, required=False)

    subject = db.subjects.get(subject_id)
    if not subject:
        raise errors.not_found()

    # rank unique within subject (well-formedness).
    for l in db.levels.values():
        if l["subject_id"] == subject_id and l["rank"] == rank:
            raise errors.invalid_request("rank must be unique within a subject.")

    if prereq_level_id is not None:
        prereq = db.levels.get(prereq_level_id)
        if not prereq:
            raise errors.not_found()
        # Curriculum integrity (priority 10): prereq must be in same subject with
        # strictly lower rank, and must not introduce a cycle.
        if prereq["subject_id"] != subject_id or prereq["rank"] >= rank:
            raise errors.prereq_cycle()
        # The new level does not exist yet, so a cycle can only arise if the
        # prereq chain (which is a DAG of strictly-decreasing ranks) somehow
        # loops back. With the strictly-lower-rank rule enforced on every node,
        # cycles are structurally impossible; we still guard defensively by
        # walking the prereq chain.
        if _would_cycle(prereq_level_id):
            raise errors.prereq_cycle()

    obj = {
        "subject_id": subject_id,
        "rank": rank,
        "label": label,
        "prereq_level_id": prereq_level_id,
        "worksheets_to_master": worksheets_to_master,
        "mastery_score_threshold": mastery_threshold,
    }
    db.stamp_create(obj)
    db.levels[obj["id"]] = obj
    return success(public(obj), status=201)


def _would_cycle(start_level_id):
    """Walk the existing prereq chain from start; report a loop if one exists."""
    seen = set()
    cur = start_level_id
    while cur is not None:
        if cur in seen:
            return True
        seen.add(cur)
        node = db.levels.get(cur)
        if not node:
            return False
        cur = node.get("prereq_level_id")
    return False


@bp.route("/curriculum-levels/<level_id>", methods=["GET"])
def get_level(level_id):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    level = db.levels.get(level_id)
    if not level:
        raise errors.not_found()
    return success(public(level))


@bp.route("/curriculum-levels", methods=["GET"])
def list_levels():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    subject_id = request.args.get("subject_id")
    prereq_level_id = request.args.get("prereq_level_id")
    items = list(db.levels.values())
    if subject_id:
        items = [l for l in items if l["subject_id"] == subject_id]
    if prereq_level_id:
        items = [l for l in items if l.get("prereq_level_id") == prereq_level_id]
    return helpers.paginate_and_respond(items)
