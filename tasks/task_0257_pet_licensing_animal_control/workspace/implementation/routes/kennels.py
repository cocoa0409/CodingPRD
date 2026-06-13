"""Kennel endpoints (PRD §3.2, §4)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import array_response, object_response
from services.core import append_audit, stamp_create, touch
from services.reqs import (body, paginate, parse_pagination, require_fields)
from services.views import kennel_view, license_view

bp = Blueprint("kennels", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}


@bp.route("/kennels", methods=["POST"])
def create_kennel():
    _, role = authenticate()
    require_role(role, {"Owner", "LicensingClerk"})
    data = body()
    require_fields(data, ["owner_id", "facility_name", "slot_capacity"])
    cap = data["slot_capacity"]
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise err("ERR_INVALID_REQUEST", "slot_capacity must be an integer >= 1.")
    if db.owners.get(data["owner_id"]) is None:
        raise err("ERR_NOT_FOUND", "Owner not found.")
    kennel = {
        "owner_id": data["owner_id"],
        "facility_name": data["facility_name"],
        "slot_capacity": cap,
        "occupied_slots": 0,
        "status": "OPEN",
    }
    stamp_create(kennel)
    db.kennels[kennel["id"]] = kennel
    return object_response(kennel_view(kennel), status=201)


@bp.route("/kennels/<kennel_id>", methods=["GET"])
def get_kennel(kennel_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    kennel = db.kennels.get(kennel_id)
    if kennel is None:
        raise err("ERR_NOT_FOUND", "Kennel not found.")
    return object_response(kennel_view(kennel))


@bp.route("/kennels/<kennel_id>/licenses", methods=["GET"])
def list_kennel_licenses(kennel_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.kennels.get(kennel_id) is None:
        raise err("ERR_NOT_FOUND", "Kennel not found.")
    limit, offset = parse_pagination()
    items = [l for l in db.licenses.values() if l.get("kennel_id") == kennel_id]
    page, total = paginate(items, limit, offset)
    return array_response([license_view(l) for l in page], limit, offset, total)


@bp.route("/kennels/<kennel_id>/suspend", methods=["POST"])
def suspend_kennel(kennel_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    kennel = db.kennels.get(kennel_id)
    if kennel is None:
        raise err("ERR_NOT_FOUND", "Kennel not found.")
    kennel["status"] = "SUSPENDED"
    touch(kennel)
    return object_response(kennel_view(kennel))
