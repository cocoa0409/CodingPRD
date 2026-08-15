"""FeeReductionApplication endpoints (PRD 3.3): SUBMITTED <-> decided loop."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_APPLICATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.serialize import serialize_application
from validate import (
    get_body, reject_unknown_fields, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("fee_reduction_applications", __name__)

BASES = ("FREE_LUNCH", "REDUCED_LUNCH", "INCOME", "OTHER")
APP_FIELDS = {"student_id", "cycle_id", "eligibility_basis", "annual_income_cents"}


@bp.post("/fee-reduction-applications")
def create_application():
    caller = require_roles(get_caller(), ["Student"])
    body = get_body()
    # Priority 2 ownership: a student files only for themselves. Evaluated on the
    # raw identity field before remaining shape checks (priority 4).
    raw_sid = body.get("student_id")
    if isinstance(raw_sid, str) and raw_sid != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "student_id must equal the caller's X-User-ID")
    reject_unknown_fields(body, APP_FIELDS)
    student_id = req_str(body, "student_id")
    cycle_id = req_str(body, "cycle_id")
    eligibility_basis = req_enum(body, "eligibility_basis", BASES)
    annual_income_cents = req_int(body, "annual_income_cents", non_negative=True)
    if student_id != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "student_id must equal the caller's X-User-ID")
    student = require_ref("students", student_id, "student_id")
    cycle = require_ref("exam_cycles", cycle_id, "cycle_id")
    # At most one application row per (student, cycle) ever — DENIED included.
    for a in db["fee_reduction_applications"].values():
        if a["student_id"] == student["id"] and a["cycle_id"] == cycle["id"]:
            raise_error(ERR_DUPLICATE_APPLICATION,
                        "an application already exists for this student and cycle")
    rec = new_record("fee_reduction_applications", {
        "student_id": student["id"],
        "cycle_id": cycle["id"],
        "eligibility_basis": eligibility_basis,
        "annual_income_cents": annual_income_cents,
        "status": "SUBMITTED",
    })
    return success_object(serialize_application(rec), status=201)


@bp.get("/fee-reduction-applications")
def list_applications():
    caller = require_roles(get_caller(), ["ApCoordinator", "Student"])
    student_filter = request.args.get("student_id")
    if caller.role == "Student":
        # Student callers only ever see their own rows.
        student_filter = caller.user_id
    filters = [
        ("student_id", student_filter),
        ("cycle_id", request.args.get("cycle_id")),
        ("status", request.args.get("status")),
    ]
    return list_response(db["fee_reduction_applications"].values(), filters,
                         serialize_application)


@bp.get("/fee-reduction-applications/<rid>")
def get_application(rid):
    caller = require_roles(get_caller(), ["ApCoordinator", "Student"])
    app = require_path_resource("fee_reduction_applications", rid)
    if caller.role == "Student" and app["student_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "students may only read their own applications")
    return success_object(serialize_application(app))


@bp.post("/fee-reduction-applications/<rid>/approve")
def approve_application(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    app = require_path_resource("fee_reduction_applications", rid)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"application in {app['status']} cannot be approved")
    app["status"] = "APPROVED"
    touch(app)
    # Subsidy/net fee/balances/rebate/DRAFT-order estimate are derived from the
    # live store at read time, so the ripple is visible immediately (PRD 2.9).
    return success_object(serialize_application(app))


@bp.post("/fee-reduction-applications/<rid>/deny")
def deny_application(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    app = require_path_resource("fee_reduction_applications", rid)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"application in {app['status']} cannot be denied")
    app["status"] = "DENIED"
    touch(app)
    return success_object(serialize_application(app))


@bp.post("/fee-reduction-applications/<rid>/resubmit")
def resubmit_application(rid):
    caller = require_roles(get_caller(), ["Student"])
    body = get_body()
    reject_unknown_fields(body, set())
    app = require_path_resource("fee_reduction_applications", rid)
    if app["student_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "only the owning student may resubmit the application")
    if app["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE,
                    f"application in {app['status']} cannot be resubmitted")
    app["status"] = "SUBMITTED"
    touch(app)
    return success_object(serialize_application(app))
