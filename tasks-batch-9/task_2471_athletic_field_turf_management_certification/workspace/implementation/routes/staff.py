"""The staff roster (PRD 3.2). Creation is exempt from identity resolution."""

import calc
import middleware
import response
import validate
from db import common_fields, db, new_id
from errors import ApiError
from routes.blueprint import bp


@bp.post("/staff-members")
def create_staff_member():
    # PRD 2.1: the single exemption from identity resolution, so that the very
    # first FacilitiesDirector row can be bootstrapped into an empty database.
    middleware.authenticate(["FacilitiesDirector"], exempt_identity=True)
    body = validate.Body(required=["full_name", "roles"],
                         optional=["employment_status"])
    full_name = body.string("full_name", 1, 120)
    roles = body.array("roles")
    employment_status = body.enum("employment_status", ["ACTIVE", "INACTIVE"],
                                 default="ACTIVE")

    # priority 24 - the role-set rule
    if (not roles or len(set(map(str, roles))) != len(roles)
            or any(not isinstance(r, str) or r not in calc.ROLE_NAMES
                   for r in roles)):
        raise ApiError("ERR_INVALID_ROLE_SET", 422,
                       "roles must be a non-empty array of distinct declared roles.")

    staff = {
        "id": new_id(),
        "full_name": full_name,
        "roles": list(roles),
        "employment_status": employment_status,
    }
    staff.update(common_fields())
    db.staff_members[staff["id"]] = staff
    return response.created(staff)


@bp.get("/staff-members/<staff_id>")
def read_staff_member(staff_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.staff_or_404(staff_id))
