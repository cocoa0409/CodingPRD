"""Staff directory endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE_STAFF_EMAIL
from middleware import authenticate, authorize
from response import success_object
from routes.helpers import list_response
from services.core import new_record, serialize_staff
from validate import get_body, req_enum, req_str

bp = Blueprint("staff", __name__)

STAFF_ROLES = ["INTAKE_COORDINATOR", "PANTRY_STAFF", "BENEFITS_COUNSELOR",
               "GRANT_REVIEWER", "SHELTER_COORDINATOR"]


@bp.post("/staff")
def create_staff():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    staff_role = req_enum(body, "staff_role", STAFF_ROLES)
    for s in db["staff"].values():
        if s["email"] == email:
            raise_error(ERR_DUPLICATE_STAFF_EMAIL, "email already used by another StaffMember")
    rec = new_record("staff", {
        "full_name": full_name,
        "email": email,
        "staff_role": staff_role,
        "status": "ACTIVE",
    })
    return success_object(serialize_staff(rec), status=201)


@bp.get("/staff")
def list_staff():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    filters = {
        "staff_role": request.args.get("staff_role"),
        "status": request.args.get("status"),
    }
    return list_response("staff", filters, serializer=serialize_staff)
