from flask import Blueprint

from db import store
import errors
import middleware
import response
from services import validate
from services.entities import stamp_create, touch, get_inspection, get_application
from services.serialize import public

bp = Blueprint("inspections", __name__)


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["InspectionOfficer"])
    data = validate.body()

    application_id = validate.require_str(data, "application_id")
    inspector_user_id = validate.require_str(data, "inspector_user_id")
    verified_employee_count = validate.optional_int(data, "verified_employee_count", 0)
    failed_item_count = validate.optional_int(data, "failed_item_count", 0)

    # existence (404)
    get_application(application_id)

    # semantic bounds (422)
    if verified_employee_count is not None and verified_employee_count < 0:
        raise errors.validation("verified_employee_count must be >= 0")
    if failed_item_count is not None and failed_item_count < 0:
        raise errors.validation("failed_item_count must be >= 0")

    rec = {
        "application_id": application_id,
        "inspector_user_id": inspector_user_id,
        "result": "SCHEDULED",
        "verified_employee_count": verified_employee_count if verified_employee_count is not None else 0,
        "failed_item_count": failed_item_count if failed_item_count is not None else 0,
    }
    stamp_create(rec)
    store.inspections[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/inspections/<iid>", methods=["GET"])
def get_one(iid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "InspectionOfficer", "Applicant"])
    rec = get_inspection(iid)
    return response.object_response(public(rec), 200)


@bp.route("/inspections/<iid>/record", methods=["POST"])
def record(iid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["InspectionOfficer"])
    insp = get_inspection(iid)
    data = validate.body()

    # well-formedness (400)
    result = validate.require_enum(data, "result", validate.INSPECTION_RESULTS)
    verified_employee_count = validate.require_int(data, "verified_employee_count")
    failed_item_count = validate.require_int(data, "failed_item_count")

    # state legality (409): only a SCHEDULED inspection may be recorded
    if insp["result"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_INSPECTION_ALREADY_RECORDED, 409,
                              "Inspection outcome already recorded")

    # semantic bounds (422)
    if verified_employee_count < 0:
        raise errors.validation("verified_employee_count must be >= 0")
    if failed_item_count < 0:
        raise errors.validation("failed_item_count must be >= 0")

    insp["result"] = result
    insp["verified_employee_count"] = verified_employee_count
    insp["failed_item_count"] = failed_item_count
    touch(insp)
    return response.object_response(public(insp), 200)
