"""Enrollment endpoints and lifecycle (PRD §3.3, §3.4)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from clock import clock
from db import fmt_ts
from services import calculations
from services.family_recompute import recompute_family

bp = Blueprint("enrollments", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}


def _parent_owns_enrollment(uid, enr):
    return helpers.parent_owns_family(uid, helpers.family_id_of_student(enr["student_id"]))


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    body = get_body()

    center_id = helpers.require_str(body, "center_id")
    student_id = helpers.require_str(body, "student_id")
    subject_id = helpers.require_str(body, "subject_id")
    diagnostic_raw_score = body.get("diagnostic_raw_score")
    if diagnostic_raw_score is not None:
        diagnostic_raw_score = helpers.require_int(body, "diagnostic_raw_score", minimum=0, maximum=100)

    # Existence (priority 3): path then body FKs, left to right.
    if center_id not in db.centers:
        raise errors.not_found()
    if student_id not in db.students:
        raise errors.not_found()
    if subject_id not in db.subjects:
        raise errors.not_found()

    obj = {
        "center_id": center_id,
        "student_id": student_id,
        "subject_id": subject_id,
        "placement_level_id": None,
        "current_level_id": None,
        "diagnostic_raw_score": diagnostic_raw_score,
        "status": "PLACEMENT_PENDING",
        "mastered_sets_in_level": 0,
        "monthly_rate_cents": 0,
    }
    db.stamp_create(obj)
    db.enrollments[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    if role == "Parent" and not _parent_owns_enrollment(uid, enr):
        raise errors.forbidden()
    return success(public(enr))


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    args = request.args
    items = list(db.enrollments.values())
    for key in ("center_id", "student_id", "subject_id", "placement_level_id",
                "current_level_id", "status"):
        val = args.get(key)
        if val:
            items = [e for e in items if e.get(key) == val]
    if role == "Parent":
        items = [e for e in items if _parent_owns_enrollment(uid, e)]
    return helpers.paginate_and_respond(items)


@bp.route("/enrollments/<enrollment_id>/place", methods=["POST"])
def place_enrollment(enrollment_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    body = get_body()

    # well-formedness of optional inputs (priority 4)
    score_in_body = body.get("diagnostic_raw_score")
    if score_in_body is not None:
        score_in_body = helpers.require_int(body, "diagnostic_raw_score", minimum=0, maximum=100)
    placement_policy = body.get("placement_policy", "STRICT")
    if placement_policy not in ("STRICT", "SUPPORTIVE"):
        raise errors.invalid_request("placement_policy must be STRICT or SUPPORTIVE.")

    # state guard (priority 6)
    if enr["status"] != "PLACEMENT_PENDING":
        raise errors.invalid_state()

    # cross-entity: center must be OPERATING
    center = db.centers.get(enr["center_id"])
    if not center or center["status"] != "OPERATING":
        raise errors.center_not_operating()

    # diagnostic_raw_score present (body overrides/fills enrollment value)
    score = score_in_body if score_in_body is not None else enr["diagnostic_raw_score"]
    if score is None:
        raise errors.diagnostic_missing()

    # run placement calc -> chosen level must belong to the subject
    level = calculations.diagnostic_placement(enr["subject_id"], score, placement_policy)
    if level is None or level["subject_id"] != enr["subject_id"]:
        raise errors.level_subject_mismatch()

    # commit
    enr["diagnostic_raw_score"] = score
    enr["placement_level_id"] = level["id"]
    enr["current_level_id"] = level["id"]
    enr["status"] = "ACTIVE"
    db.touch(enr)

    # stage enrollment fee for the student (one-time)
    student = db.students.get(enr["student_id"])
    if student and not student["enrollment_fee_charged"]:
        student["enrollment_fee_charged"] = True
        db.touch(student)

    # cascade: recompute sibling_count + monthly_rate across the family
    family_id = helpers.family_id_of_student(enr["student_id"])
    recompute_family(family_id)
    return success(public(enr))


@bp.route("/enrollments/<enrollment_id>/pause", methods=["POST"])
def pause_enrollment(enrollment_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    if enr["status"] != "ACTIVE":
        raise errors.invalid_state()
    enr["status"] = "PAUSED"
    db.touch(enr)
    recompute_family(helpers.family_id_of_student(enr["student_id"]))
    return success(public(enr))


@bp.route("/enrollments/<enrollment_id>/resume", methods=["POST"])
def resume_enrollment(enrollment_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    if enr["status"] != "PAUSED":
        raise errors.invalid_state()
    center = db.centers.get(enr["center_id"])
    if not center or center["status"] != "OPERATING":
        raise errors.center_not_operating()
    enr["status"] = "ACTIVE"
    db.touch(enr)
    recompute_family(helpers.family_id_of_student(enr["student_id"]))
    return success(public(enr))


@bp.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw_enrollment(enrollment_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    if enr["status"] not in ("ACTIVE", "PAUSED", "PLACEMENT_PENDING"):
        raise errors.invalid_state()

    enr["status"] = "WITHDRAWN"
    db.touch(enr)

    # Future BOOKED attendance (session.start_at > clock now) -> CANCELLED,
    # recompute each affected session's booked_seat_count. Worksheets left
    # unchanged (no further grading allowed; enforced via status != ACTIVE).
    from services import session_ops
    now = clock.now()
    for rec in db.attendance.values():
        if rec["enrollment_id"] != enrollment_id or rec["status"] != "BOOKED":
            continue
        sess = db.sessions.get(rec["session_id"])
        if not sess:
            continue
        start_at = _parse_iso(sess["start_at"])
        if start_at is not None and start_at > now:
            rec["status"] = "CANCELLED"
            db.touch(rec)
            session_ops.recompute_booked_seat_count(sess)

    recompute_family(helpers.family_id_of_student(enr["student_id"]))
    return success(public(enr))


@bp.route("/enrollments/<enrollment_id>/report", methods=["GET"])
def enrollment_report(enrollment_id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        raise errors.not_found()
    if role == "Parent" and not _parent_owns_enrollment(uid, enr):
        raise errors.forbidden()

    # Per-level mastered counts (distinct mastered set_numbers per level).
    per_level = {}
    for w in db.worksheets.values():
        if w["enrollment_id"] != enrollment_id or w["status"] != "MASTERED":
            continue
        per_level.setdefault(w["level_id"], set()).add(w["set_number"])
    per_level_counts = {lid: len(sets) for lid, sets in per_level.items()}

    data = public(enr)
    data["per_level_mastered_counts"] = per_level_counts
    return success(data)


def _parse_iso(s):
    from datetime import datetime, timezone
    if not s:
        return None
    try:
        txt = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
