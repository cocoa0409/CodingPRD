"""Resource (chair/room) routes: create, fetch, list (PRD §3.1)."""
from flask import Blueprint, request

import db
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, public
import validate as v
from routes.common import auth, json_body, list_response, ALL_ROLES

bp = Blueprint("resources", __name__)

RESOURCE_TYPES = {"CHAIR", "ROOM"}
STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


@bp.post("/resources")
def create_resource():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    label = v.req_str(body, "label")
    resource_type = v.req_enum(body, "resource_type", RESOURCE_TYPES)
    status = v.opt_enum(body, "status", STATUSES, default="ACTIVE")

    resource = {
        "salon_id": salon["id"],
        "label": label,
        "resource_type": resource_type,
        "status": status,
    }
    stamp_create(resource)
    db.resources[resource["id"]] = resource
    return success(public(resource), status=201)


@bp.get("/resources/<resource_id>")
def get_resource(resource_id):
    auth(ALL_ROLES)
    resource = get_or_404(db.resources, resource_id)
    return success(public(resource), status=200)


@bp.get("/resources")
def list_resources():
    auth(ALL_ROLES)
    salon_id = request.args.get("salon_id")
    resource_type = request.args.get("resource_type")
    status = request.args.get("status")

    def pred(r):
        if salon_id is not None and r["salon_id"] != salon_id:
            return False
        if resource_type is not None and r["resource_type"] != resource_type:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, meta = list_response(db.resources, pred)
    return success(page, status=200, response_type="array", pagination=meta)
