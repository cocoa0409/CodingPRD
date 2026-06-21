"""Technician endpoints (PRD §3.1).

Technician: full_name, license_class (JOURNEYMAN|MASTER), service_zone,
hourly_rate_cents, on_call (default false).
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_bool,
                     require_fields, require_nonneg_int, require_enum,
                     require_string, serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("technicians", __name__)

LICENSE_CLASSES = {"JOURNEYMAN", "MASTER"}


@bp.post("/v1/technicians")
def create_technician():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["full_name", "license_class", "service_zone", "hourly_rate_cents"])
    require_string(body["full_name"], "full_name")
    require_enum(body["license_class"], LICENSE_CLASSES, "license_class")
    require_string(body["service_zone"], "service_zone")
    require_nonneg_int(body["hourly_rate_cents"], "hourly_rate_cents")

    on_call = body.get("on_call", False)
    if on_call is None:
        on_call = False
    require_bool(on_call, "on_call")

    record = {
        "full_name": body["full_name"],
        "license_class": body["license_class"],
        "service_zone": body["service_zone"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "on_call": on_call,
    }
    db.stamp_new(record)
    db.technicians[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/technicians/<technician_id>")
def get_technician(technician_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    record = db.technicians.get(technician_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Technician not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/technicians")
def list_technicians():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    limit, offset = parse_pagination()
    service_zone = request.args.get("service_zone")

    items = list(db.technicians.values())
    if service_zone is not None:
        items = [t for t in items if t["service_zone"] == service_zone]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
