from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, is_int, paginate, require_fields

bp = Blueprint("delineations", __name__)

COORD = "MedicalStaffCoordinator"


@bp.route("/mso/delineations", methods=["POST"])
@require_roles(COORD)
def create_delineation():
    body = get_body()
    # Rung 3: existence.
    app_id = body.get("application_id")
    app = None
    if app_id is not None:
        app = db.applications.get(app_id)
        if app is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "AppointmentApplication not found")
    # Rung 4: OCC on the application's version.
    if app is not None and "expected_application_version" in body \
            and body["expected_application_version"] is not None:
        if body["expected_application_version"] != app["version"]:
            errors.raise_err(errors.ERR_STALE_VERSION,
                             "expected_application_version does not match the "
                             "application's current version")
    # Rung 10: the requested line must be defined for the member's specialty.
    privilege_line = body.get("privilege_line")
    if app is not None and isinstance(privilege_line, str):
        member = db.members.get(app["member_id"])
        if member is not None and \
                services.criteria_for(member, privilege_line) is None:
            errors.raise_err(errors.ERR_PRIVILEGE_LINE_UNKNOWN,
                             "privilege_line is not defined in the "
                             "SpecialtyCriteria for the member's specialty")
    # Rung 11: input shape.
    require_fields(body, ["application_id", "privilege_line",
                          "documented_training_months",
                          "documented_cases_24mo",
                          "expected_application_version"])
    for f in ("documented_training_months", "documented_cases_24mo"):
        if not is_int(body[f]) or body[f] < 0:
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             f"{f} must be a non-negative integer")
    if not isinstance(body["expected_application_version"], int) \
            or isinstance(body["expected_application_version"], bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "expected_application_version must be an integer")

    rec = services.base_record()
    rec.update({
        "application_id": app_id,
        "privilege_line": privilege_line,
        "documented_training_months": body["documented_training_months"],
        "documented_cases_24mo": body["documented_cases_24mo"],
        "delineation_status": "REQUESTED",
        "satisfaction_tier": None,
        "satisfaction_score": None,
    })
    db.delineations[rec["id"]] = rec
    # Side effect: the parent application's version advances.
    services.touch(app)
    return ok_object(serializers.delineation(rec), 201)


@bp.route("/mso/delineations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_delineations():
    items, limit, offset, total = paginate(
        db.delineations.values(), serializers.delineation,
        ["application_id", "delineation_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/delineations/<did>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_delineation(did):
    rec = db.delineations.get(did)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "PrivilegeDelineation not found")
    return ok_object(serializers.delineation(rec))


@bp.route("/mso/delineations/<did>/evaluate", methods=["POST"])
@require_roles(COORD)
def evaluate_delineation(did):
    get_body()
    rec = db.delineations.get(did)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "PrivilegeDelineation not found")
    if rec["delineation_status"] != "REQUESTED":
        errors.raise_err(errors.ERR_DELINEATION_NOT_EVALUABLE,
                         "Delineation is not in REQUESTED")
    app = db.applications.get(rec["application_id"])
    if app is None or app["application_status"] not in (
            "SUBMITTED", "PSV_IN_PROGRESS", "PSV_COMPLETE"):
        errors.raise_err(errors.ERR_APPLICATION_NOT_IN_REVIEW,
                         "Parent application is not in a review state")
    services.evaluate_delineation(rec)
    return ok_object(serializers.delineation(rec))
