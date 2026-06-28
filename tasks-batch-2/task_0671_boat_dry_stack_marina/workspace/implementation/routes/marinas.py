from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_INVALID_REQUEST
from services.common import (
    stamp_create, get_json_body, require_fields, require_string,
    parse_pagination, paginate,
)
from services.lookups import get_marina
from services.serialize import marina_view

marinas_bp = Blueprint("marinas", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}


@marinas_bp.route("/marina/marinas", methods=["POST"])
def create_marina():
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["name"])
    require_string(body["name"], "name")

    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    require_string(timezone, "timezone")

    service_minutes = body.get("forklift_service_minutes", 30)
    if service_minutes is None:
        service_minutes = 30
    if isinstance(service_minutes, bool) or not isinstance(service_minutes, int) or service_minutes < 1:
        raise err(ERR_INVALID_REQUEST, "forklift_service_minutes must be an integer >= 1.")

    buffer_minutes = body.get("forklift_buffer_minutes", 15)
    if buffer_minutes is None:
        buffer_minutes = 15
    if isinstance(buffer_minutes, bool) or not isinstance(buffer_minutes, int) or buffer_minutes < 0:
        raise err(ERR_INVALID_REQUEST, "forklift_buffer_minutes must be an integer >= 0.")

    with db.lock:
        rec = {
            "name": body["name"],
            "timezone": timezone,
            "forklift_service_minutes": service_minutes,
            "forklift_buffer_minutes": buffer_minutes,
        }
        stamp_create(rec)
        db.marinas[rec["id"]] = rec
    return object_response(marina_view(rec), 201)


@marinas_bp.route("/marina/marinas/<marina_id>", methods=["GET"])
def fetch_marina(marina_id):
    require_role(READ_ROLES)
    rec = get_marina(marina_id)
    return object_response(marina_view(rec), 200)


@marinas_bp.route("/marina/marinas", methods=["GET"])
def list_marinas():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.marinas.values())
    page, total = paginate(records, limit, offset)
    return array_response([marina_view(r) for r in page], limit, offset, total)
