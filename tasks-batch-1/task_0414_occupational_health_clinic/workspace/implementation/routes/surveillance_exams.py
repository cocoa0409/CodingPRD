"""Surveillance-exam endpoints (PRD §3.8, §3.12)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.calculations import surveillance_outcome
from services.common import base_entity, touch
from services.serialize import public

bp = Blueprint("surveillance_exams", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
PANEL_TO_KIND = {"AUDIOMETRIC": "AUDIOMETRIC", "RESPIRATOR_FIT": "RESPIRATOR_FIT"}
RESPIRATOR_CLASSES = {"HALF_MASK", "FULL_FACEPIECE"}


def _opt_int(body, name):
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return val


@bp.route("/clinic/surveillance-exams", methods=["POST"])
def create_surveillance_exam():
    caller = authenticate()
    require_role(caller, {"Clinician"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        encounter_id = body.get("encounter_id")
        enc = db.encounters.get(encounter_id) if encounter_id is not None else None
        if enc is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "encounter missing or not found")

        # Priority 5: body well-formedness (optional measurement fields).
        baseline_db = _opt_int(body, "baseline_threshold_db")
        current_db = _opt_int(body, "current_threshold_db")
        fit_factor = _opt_int(body, "fit_factor")
        respirator_class = body.get("respirator_class")
        if respirator_class is not None and respirator_class not in RESPIRATOR_CLASSES:
            raise err(errors.ERR_INVALID_REQUEST, "invalid respirator_class")

        exam_kind = PANEL_TO_KIND.get(enc.get("panel_code"))

        if enc["status"] != "IN_PROGRESS":
            raise err(errors.ERR_ENCOUNTER_NOT_SCHEDULED,
                      "Encounter must be IN_PROGRESS to create a surveillance exam")

        ex = base_entity()
        ex.update({
            "encounter_id": encounter_id,
            "employer_id": enc["employer_id"],
            "worker_id": enc["worker_id"],
            "exam_kind": exam_kind,
            "baseline_threshold_db": baseline_db,
            "current_threshold_db": current_db,
            "fit_factor": fit_factor,
            "respirator_class": respirator_class,
            "outcome": None,
            "status": "SCHEDULED",
        })
        db.surveillance_exams[ex["id"]] = ex

        enc["status"] = "PENDING_RESULTS"
        touch(enc)

        return object_response(public(ex), 201)


@bp.route("/clinic/surveillance-exams", methods=["GET"])
def list_surveillance_exams():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.surveillance_exams.values())
    for key in ("encounter_id", "employer_id", "worker_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/surveillance-exams/<ex_id>", methods=["GET"])
def get_surveillance_exam(ex_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    ex = lookup.get_surveillance_exam(ex_id)
    return object_response(public(ex), 200)


@bp.route("/clinic/surveillance-exams/<ex_id>/record", methods=["POST"])
def record(ex_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        ex = lookup.get_surveillance_exam(ex_id)
        if ex["status"] != "SCHEDULED":
            raise err(errors.ERR_EXAM_NOT_SCHEDULED, "Exam must be SCHEDULED to record")

        if ex["exam_kind"] == "AUDIOMETRIC":
            if ex.get("baseline_threshold_db") is None or ex.get("current_threshold_db") is None:
                raise err(errors.ERR_EXAM_MISSING_MEASUREMENTS,
                          "AUDIOMETRIC requires baseline_threshold_db and current_threshold_db")
        elif ex["exam_kind"] == "RESPIRATOR_FIT":
            if ex.get("fit_factor") is None or ex.get("respirator_class") is None:
                raise err(errors.ERR_EXAM_MISSING_MEASUREMENTS,
                          "RESPIRATOR_FIT requires fit_factor and respirator_class")

        outcome = surveillance_outcome(
            ex["exam_kind"],
            ex.get("baseline_threshold_db"),
            ex.get("current_threshold_db"),
            ex.get("fit_factor"),
            ex.get("respirator_class"),
        )
        ex["outcome"] = outcome
        ex["status"] = "RECORDED"
        touch(ex)
        return object_response(public(ex), 200)


@bp.route("/clinic/surveillance-exams/<ex_id>/finalize", methods=["POST"])
def finalize(ex_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        ex = lookup.get_surveillance_exam(ex_id)
        if ex["status"] != "RECORDED":
            raise err(errors.ERR_EXAM_NOT_RECORDED, "Exam must be RECORDED to finalize")
        ex["status"] = "FINALIZED"
        # Record the finalization date (employer current_date) for recheck windows.
        employer = db.employers.get(ex["employer_id"])
        if employer is not None:
            ex["_finalized_on"] = employer["current_date"]
        touch(ex)
        return object_response(public(ex), 200)


@bp.route("/clinic/surveillance-exams/<ex_id>/cancel", methods=["POST"])
def cancel(ex_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        ex = lookup.get_surveillance_exam(ex_id)
        if ex["status"] not in ("SCHEDULED", "RECORDED"):
            raise err(errors.ERR_EXAM_NOT_CANCELLABLE,
                      "Exam must be SCHEDULED or RECORDED to cancel")
        ex["status"] = "CANCELLED"
        touch(ex)
        return object_response(public(ex), 200)
