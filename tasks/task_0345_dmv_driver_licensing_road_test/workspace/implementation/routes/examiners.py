"""Examiner endpoints."""
from flask import Blueprint, request

from db import db as store
from db import LICENSE_CLASSES
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services.common import new_common, get_json_body, paginate, require_fields, require_str
from services.lookup import fetch

bp = Blueprint("examiners", __name__)


@bp.post("/examiners")
def create_examiner():
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer"})
    body = get_json_body()
    require_fields(body, ["full_name", "certified_classes", "opaque_user_id"])
    full_name = require_str(body, "full_name")
    opaque_user_id = require_str(body, "opaque_user_id")
    certified = body["certified_classes"]
    if not isinstance(certified, list) or not certified:
        raise err("ERR_INVALID_REQUEST", "certified_classes must be a non-empty array")
    for c in certified:
        if c not in LICENSE_CLASSES:
            raise err("ERR_INVALID_REQUEST", f"invalid license class: {c}")
    examiner = new_common(
        full_name=full_name,
        certified_classes=certified,
        opaque_user_id=opaque_user_id,
    )
    store.examiners[examiner["id"]] = examiner
    return success(serialize.examiner(examiner), 201, "object")


@bp.get("/examiners/<eid>")
def get_examiner(eid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer", "Examiner"})
    examiner = fetch(store.examiners, eid)
    return success(serialize.examiner(examiner), 200, "object")


@bp.get("/examiners/<eid>/road-test-appointments")
def list_examiner_appointments(eid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer", "Examiner"})
    fetch(store.examiners, eid)
    status = request.args.get("status")
    items = [
        a for a in store.road_test_appointments.values()
        if a["examiner_id"] == eid and (status is None or a["status"] == status)
    ]
    data, pagination = paginate(items, serialize.road_test_appointment)
    return success(data, 200, "array", pagination)
