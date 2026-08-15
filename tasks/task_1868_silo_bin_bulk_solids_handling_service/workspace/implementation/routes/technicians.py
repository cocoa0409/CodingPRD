"""Technician endpoints."""
from flask import Blueprint

import errors
from db import store, new_id, now_iso
from middleware import require_auth, require_role
from response import success_object
from services import serialize
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_bool, as_number, check_range)

bp = Blueprint("technicians", __name__)


@bp.route("/technicians", methods=["POST"])
def create_technician():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"name", "weekly_capacity_hours", "certifications", "active"})
    require_fields(body, ["name", "weekly_capacity_hours"])
    name = as_string(body["name"], "name")
    weekly = as_number(body["weekly_capacity_hours"], "weekly_capacity_hours")
    check_range(weekly, "weekly_capacity_hours", 0, None, min_exclusive=True)
    certs = []
    if "certifications" in body:
        if not isinstance(body["certifications"], list):
            raise errors.validation("certifications must be an array")
        for c in body["certifications"]:
            if not isinstance(c, str):
                raise errors.validation("certifications must contain strings")
        certs = list(body["certifications"])
    active = True
    if "active" in body:
        active = as_bool(body["active"], "active")

    require_role(ctx, {"ServiceManager"})

    ts = now_iso()
    tech = {
        "id": new_id(),
        "name": name,
        "weekly_capacity_hours": weekly,
        "certifications": certs,
        "active": active,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.technicians[tech["id"]] = tech
    return success_object(serialize.serialize_technician(tech), status=201)


@bp.route("/technicians/<tech_id>", methods=["GET"])
def get_technician(tech_id):
    require_auth()
    t = store.technicians.get(tech_id)
    if t is None:
        raise errors.not_found(errors.ERR_TECHNICIAN_NOT_FOUND, "Technician not found")
    return success_object(serialize.serialize_technician(t))
