"""ConflictingInfoCase endpoints (PRD 3.4) with segregation of duties."""
from flask import Blueprint, request

from errors import (
    raise_error, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, public, touch
from validate import (
    get_body, req_str, opt_int, require_path_resource, deferred_body_ref,
)

bp = Blueprint("conflicts", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]


@bp.post("/conflicting-info-cases")
def create_case():
    caller = authorized(["AidOfficer"])
    body = get_body()
    # Rung 4: body foreign keys (absent keys defer to the rung-9 shape check).
    student = deferred_body_ref("students", body, "student_id")
    aid_year = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 9: shape.
    req_str(body, "student_id")
    req_str(body, "aid_year_id")
    subject_field = req_str(body, "subject_field")
    claimed = opt_int(body, "claimed_value_cents", None)
    rec = new_record("conflicting_info_cases", {
        "student_id": student["id"],
        "aid_year_id": aid_year["id"],
        "subject_field": subject_field,
        "claimed_value_cents": claimed,
        "status": "OPEN",
        "resolution": None,
        "resolved_by_user_id": None,
        "opened_by_user_id": caller.user_id,
    })
    return success_object(public(rec), status=201)


@bp.get("/conflicting-info-cases")
def list_cases():
    authorized(DIRECTOR_OFFICER)
    return list_response("conflicting_info_cases", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/conflicting-info-cases/<rid>")
def get_case(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("conflicting_info_cases", rid)
    return success_object(public(rec))


@bp.post("/conflicting-info-cases/<rid>/substantiate")
def substantiate(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("conflicting_info_cases", rid)
    if case["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected OPEN")
    case["status"] = "SUBSTANTIATED"
    touch(case)
    return success_object(public(case))


@bp.post("/conflicting-info-cases/<rid>/unsubstantiate")
def unsubstantiate(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("conflicting_info_cases", rid)
    if case["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected OPEN")
    case["status"] = "UNSUBSTANTIATED"
    touch(case)
    return success_object(public(case))


def _resolve(case, caller, from_status, to_status):
    # Rung 5: state legality.
    if case["status"] != from_status:
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected {from_status}")
    # Rung 7: segregation of duties — the resolving caller must differ from
    # opened_by_user_id. Rung 7 precedes rung 9 (request shape).
    if caller.user_id == case["opened_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the resolving caller must differ from the officer who opened "
                    "the case")
    # Rung 9: shape.
    body = get_body()
    resolution = req_str(body, "resolution")
    case["status"] = to_status
    case["resolution"] = resolution
    case["resolved_by_user_id"] = caller.user_id
    touch(case)
    return case


@bp.post("/conflicting-info-cases/<rid>/resolve-requires-correction")
def resolve_requires_correction(rid):
    caller = authorized(["AidOfficer"])
    case = require_path_resource("conflicting_info_cases", rid)
    _resolve(case, caller, "SUBSTANTIATED", "RESOLVED_REQUIRES_CORRECTION")
    return success_object(public(case))


@bp.post("/conflicting-info-cases/<rid>/resolve")
def resolve(rid):
    caller = authorized(["AidOfficer"])
    case = require_path_resource("conflicting_info_cases", rid)
    _resolve(case, caller, "UNSUBSTANTIATED", "RESOLVED")
    return success_object(public(case))
