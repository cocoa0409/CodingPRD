"""MachineResource endpoints (PRD §3.6)."""

from flask import request

from db import STORE, new_record
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_resource
from services import get_resource
from util import (
    GRADES,
    as_enum,
    as_positive_decimal,
    as_string,
    body_dict,
    req_present,
)

from routes import bp

RESOURCE_TYPES = {"FORMING_STATION", "INSPECTION_BOOTH"}


@bp.route("/machine-resources", methods=["POST"])
@endpoint({"ProductionScheduler"})
def create_resource(user_id, role):
    body = body_dict(request.get_json(silent=True))
    resource_code = as_string(req_present(body, "resource_code"), "resource_code")
    resource_type = as_enum(req_present(body, "resource_type"), "resource_type", RESOURCE_TYPES)
    grade = as_enum(req_present(body, "cleanliness_grade"), "cleanliness_grade", GRADES)
    rate = as_positive_decimal(req_present(body, "machine_rate_per_hour"), "machine_rate_per_hour")

    rec = new_record()
    rec.update({
        "resource_code": resource_code,
        "resource_type": resource_type,
        "cleanliness_grade": grade,
        "machine_rate_per_hour": rate,
    })
    STORE["machine_resources"][rec["id"]] = rec
    return ok_object(ser_resource(rec), 201)


@bp.route("/machine-resources", methods=["GET"])
@endpoint(ANY_ROLE)
def list_resources(user_id, role):
    items = list(STORE["machine_resources"].values())
    resource_type = request.args.get("resource_type")
    if resource_type is not None:
        items = [r for r in items if r["resource_type"] == resource_type]
    return list_response(items, ser_resource)


@bp.route("/machine-resources/<resourceId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_resource(user_id, role, resourceId):
    return ok_object(ser_resource(get_resource(resourceId)))
