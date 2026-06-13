"""BookableResource endpoints (PRD §3.7)."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize
from routes import helpers

bp = Blueprint("resources", __name__)

RESOURCE_KINDS = {"ROOM", "COMPUTER"}
SERVICE_STATUSES = {"IN_SERVICE", "OUT_OF_SERVICE"}


@bp.post("/library/resources")
def create_resource():
    caller = authenticate()
    require_roles(caller, {ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["branch_id", "resource_kind", "label"])
    branch_id = helpers.require_string(body, "branch_id")
    resource_kind = helpers.enum_value(body, "resource_kind", RESOURCE_KINDS, required=True)
    label = helpers.require_string(body, "label")

    helpers.find_or_404(db.branches, branch_id)

    capacity = helpers.optional_int(body, "capacity", 1)
    if capacity < 1:
        raise errors.invalid_request("capacity must be >= 1.")

    record = {
        "branch_id": branch_id,
        "resource_kind": resource_kind,
        "label": label,
        "capacity": capacity,
        "status": "IN_SERVICE",
    }
    db.stamp_create(record)
    db.resources[record["id"]] = record
    return response.object_response(serialize.resource(record), status=201)


@bp.get("/library/resources/<rid>")
def get_resource(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.resources, rid)
    return response.object_response(serialize.resource(record))


@bp.get("/library/resources")
def list_resources():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    branch_id = request.args.get("branch_id")
    resource_kind = helpers.enum_filter("resource_kind", RESOURCE_KINDS)
    records = [
        r for r in db.resources.values()
        if (branch_id is None or r["branch_id"] == branch_id)
        and (resource_kind is None or r["resource_kind"] == resource_kind)
    ]
    return helpers.list_response(records, serialize.resource)


@bp.post("/library/resources/<rid>/set-service-status")
def set_service_status(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_MANAGER})
    record = helpers.find_or_404(db.resources, rid)
    body = helpers.get_json_body()
    new_status = helpers.enum_value(body, "status", SERVICE_STATUSES, required=True)
    record["status"] = new_status
    db.touch(record)
    return response.object_response(serialize.resource(record))
