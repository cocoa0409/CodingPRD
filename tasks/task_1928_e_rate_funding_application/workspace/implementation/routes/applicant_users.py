"""ApplicantUser provisioning endpoints (PRD 3.1)."""
from flask import Blueprint, request

from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from validate import get_body, check_allowed, req_str, req_enum, require_ref

bp = Blueprint("applicant_users", __name__, url_prefix="/erate")


@bp.post("/applicant-users")
def create_user():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"applicant_id", "display_name", "function"})
    applicant_id = req_str(body, "applicant_id")
    display_name = req_str(body, "display_name")
    function = req_enum(body, "function", ("COORDINATOR", "CERTIFIER"))
    require_ref("applicants", applicant_id, "applicant_id")
    rec = new_record("applicant_users", {
        "applicant_id": applicant_id,
        "display_name": display_name,
        "function": function,
    })
    return success_object(public(rec), 201)


@bp.get("/applicant-users")
def list_users():
    return list_collection("applicant_users", {
        "applicant_id": request.args.get("applicant_id"),
    })


@bp.get("/applicant-users/<rid>")
def get_user(rid):
    return get_one("applicant_users", rid)
