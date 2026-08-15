"""CoveredPerson endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles, insider_owns_read
from response import success, paginate
from services.core import (new_entity, serialize, serialize_person, sort_created,
                           get_or_404, DESIGNATIONS)
from util import Body

bp = Blueprint("covered_persons", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "CommitteeMember", "LegalAdmin")


@bp.post("/covered-persons")
def create_person():
    require_roles("LegalAdmin")
    body = Body()
    full_name = body.get_str("full_name")
    email = body.get_str("email")
    designation = body.get_enum("designation", DESIGNATIONS)
    department = body.get_str("department")
    body.flush()
    if any(p["email"] == email for p in STORE.covered_persons.values()):
        raise err(ERR_INVALID_REQUEST, "email must be unique across covered persons")
    p = new_entity()
    p.update({
        "full_name": full_name,
        "email": email,
        "designation": designation,
        "department": department,
        "status": "ACTIVE",
        "suspended_until": None,
        "policy_ack_current": False,
        "training_current": False,
        "compliance_hold": False,
        "_suspended_until_dt": None,
    })
    STORE.covered_persons[p["id"]] = p
    return success(serialize_person(p), 201)


@bp.get("/covered-persons/<pid>")
def get_person(pid):
    require_roles(*READ_ROLES)
    # For covered persons the path id IS the owner id, so the Insider
    # ownership check (ladder step 2) runs before existence (step 3).
    insider_owns_read(pid)
    p = get_or_404("covered_persons", pid, "covered person")
    return success(serialize_person(p))


@bp.get("/covered-persons")
def list_persons():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.covered_persons.values())
    designation = request.args.get("designation")
    status = request.args.get("status")
    if designation is not None:
        items = [p for p in items if p["designation"] == designation]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([serialize_person(p) for p in items])
