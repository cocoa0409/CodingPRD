"""TrainingEnrollment endpoints: create, list, get, progress, complete."""

from flask import request, Blueprint

import db
import util
from util import D
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("training", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]


def _get_enrollment_or_404(enrollment_id):
    e = db.training_enrollments.get(enrollment_id)
    if e is None:
        raise_err("ERR_NOT_FOUND", "TrainingEnrollment not found")
    return e


@bp.route("/training-enrollments", methods=["POST"])
def create_enrollment():
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("cycle_id", "volunteer_id"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
        if not isinstance(body[f], str):
            raise_err("ERR_INVALID_REQUEST", f"{f} must be a string")
    cycle = db.program_cycles.get(body["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "cycle_id does not resolve")
    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise_err("ERR_NOT_FOUND", "volunteer_id does not resolve")
    # posture (priority 7)
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Training enrollment requires an OPEN cycle")
    # volunteer must be TRAINEE
    if vol["status"] != "TRAINEE":
        raise_err("ERR_INVALID_REQUEST", "Volunteer must be a TRAINEE to enroll")
    # duplicate ENROLLED per (volunteer, cycle)
    for e in db.training_enrollments.values():
        if e["volunteer_id"] == vol["id"] and e["cycle_id"] == cycle["id"] and e["status"] == "ENROLLED":
            raise_err("ERR_DUPLICATE_ENROLLMENT", "An ENROLLED enrollment already exists for this volunteer and cycle")
    if cycle["enrolled_count"] >= cycle["training_capacity"]:
        raise_err("ERR_TRAINING_FULL", "Cycle training capacity reached")

    enrollment = util.new_resource({
        "cycle_id": cycle["id"],
        "volunteer_id": vol["id"],
        "modules_completed": 0,
        "quiz_average": 0.0,
        "status": "ENROLLED",
        "completed_at": None,
    })
    db.training_enrollments[enrollment["id"]] = enrollment
    cycle["enrolled_count"] += 1
    util.touch(cycle)
    return success_object(enrollment, 201)


@bp.route("/training-enrollments", methods=["GET"])
def list_enrollments():
    auth_context(ALL_ROLES)
    items = list(db.training_enrollments.values())
    for param in ("cycle_id", "volunteer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/training-enrollments/<enrollmentId>", methods=["GET"])
def get_enrollment(enrollmentId):
    auth_context(ALL_ROLES)
    return success_object(_get_enrollment_or_404(enrollmentId))


@bp.route("/training-enrollments/<enrollmentId>/progress", methods=["POST"])
def progress_enrollment(enrollmentId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("modules_completed", "quiz_average"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    mc = body["modules_completed"]
    qa = body["quiz_average"]
    if not isinstance(mc, int) or isinstance(mc, bool):
        raise_err("ERR_INVALID_REQUEST", "modules_completed must be an integer")
    if mc < 0:
        raise_err("ERR_INVALID_FIELD_VALUE", "modules_completed must be >= 0")
    if not isinstance(qa, (int, float)) or isinstance(qa, bool):
        raise_err("ERR_INVALID_REQUEST", "quiz_average must be a number")
    if D(qa) < 0 or D(qa) > 100:
        raise_err("ERR_INVALID_FIELD_VALUE", "quiz_average must be 0..100")

    enrollment = _get_enrollment_or_404(enrollmentId)
    cycle = db.program_cycles.get(enrollment["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "Enrollment's cycle not found")
    # posture (priority 7) precedes target state (priority 8)
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Enrollment progress requires an OPEN cycle")
    if enrollment["status"] != "ENROLLED":
        raise_err("ERR_ENROLLMENT_NOT_ENROLLED", "Enrollment must be ENROLLED")
    enrollment["modules_completed"] = mc
    enrollment["quiz_average"] = float(D(qa))
    util.touch(enrollment)
    return success_object(enrollment)


@bp.route("/training-enrollments/<enrollmentId>/complete", methods=["POST"])
def complete_enrollment(enrollmentId):
    auth_context(PC)
    enrollment = _get_enrollment_or_404(enrollmentId)
    cycle = db.program_cycles.get(enrollment["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "Enrollment's cycle not found")
    # posture (priority 7) precedes target state (priority 8)
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Enrollment completion requires an OPEN cycle")
    if enrollment["status"] != "ENROLLED":
        raise_err("ERR_ENROLLMENT_NOT_ENROLLED", "Enrollment must be ENROLLED")

    passes = (enrollment["modules_completed"] >= cycle["training_module_count"]
              and D(enrollment["quiz_average"]) >= D(cycle["training_pass_quiz_average"]))
    enrollment["status"] = "COMPLETED" if passes else "FAILED"
    enrollment["completed_at"] = util.logical_clock_iso()
    util.touch(enrollment)
    cycle["enrolled_count"] = max(0, cycle["enrolled_count"] - 1)
    util.touch(cycle)

    if passes:
        vol = db.volunteers.get(enrollment["volunteer_id"])
        if vol is not None and vol["status"] == "TRAINEE":
            vol["status"] = "ACTIVE"
            util.touch(vol)
            # provision PENDING record when cycle OPEN and none exists
            if calc.record_for(vol["id"], cycle["id"]) is None:
                calc.provision_record(vol["id"], cycle["id"])
    return success_object(enrollment)
