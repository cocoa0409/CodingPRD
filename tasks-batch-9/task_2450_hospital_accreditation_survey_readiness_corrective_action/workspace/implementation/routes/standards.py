"""Standards and the accountability map (PRD 3.1)."""

from flask import Blueprint, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_owner_assignment,
    get_standard,
    opt_str,
    page,
    pagination,
    req_enum,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("standards", __name__)


@bp.get("/accreditation/standards/<standard_id>")
def read_standard(standard_id):
    require_roles(*ALL_ROLES)
    standard = get_standard(standard_id)
    return object_response(serialize.standard(standard))


@bp.post("/accreditation/standards/<standard_id>/owner-assignments")
def create_owner_assignment(standard_id):
    require_roles("AccreditationDirector")
    b = body()
    owner_user_id = req_str(b, "owner_user_id")
    designation = req_enum(b, "designation", calc.DESIGNATIONS)

    standard = get_standard(standard_id)

    # Rung 39
    for existing in cascade.active_assignments(standard["id"]):
        if existing["owner_user_id"] == owner_user_id:
            raise ApiError("ERR_DUPLICATE_OWNER_ASSIGNMENT")

    assignment = base_entity("OwnerAssignment")
    assignment.update(
        {
            "standard_id": standard["id"],
            "owner_user_id": owner_user_id,
            "designation": designation,
            "status": "ACTIVE",
            "revoked_at": None,
        }
    )
    db.owner_assignments[assignment["id"]] = assignment

    cascade.on_owner_added(standard)

    return object_response(serialize.owner_assignment(assignment), 201)


@bp.get("/accreditation/standards/<standard_id>/owner-assignments")
def list_owner_assignments(standard_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    standard = get_standard(standard_id)
    status_filter = request.args.get("status")
    result = [a for a in rows(db.owner_assignments) if a["standard_id"] == standard["id"]]
    if status_filter:
        result = [a for a in result if a["status"] == status_filter]
    items, total = page(result, limit, offset)
    return array_response([serialize.owner_assignment(a) for a in items], limit, offset, total)


@bp.post("/accreditation/owner-assignments/<assignment_id>/revoke")
def revoke_owner_assignment(assignment_id):
    require_roles("AccreditationDirector")
    b = body()
    opt_str(b, "reason")

    assignment = get_owner_assignment(assignment_id)

    # Rung 22
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_OWNER_ASSIGNMENT_ALREADY_REVOKED")

    assignment["status"] = "REVOKED"
    assignment["revoked_at"] = db.clock
    touch(assignment)

    standard = db.standards[assignment["standard_id"]]
    cascade.on_owner_revoked(standard)

    return object_response(serialize.owner_assignment(assignment))
