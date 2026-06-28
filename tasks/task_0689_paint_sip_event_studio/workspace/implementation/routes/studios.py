"""Studio (room) endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response

bp = Blueprint("studios", __name__)


@bp.post("/studio-ops/studios")
def create_studio():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    name = helpers.as_str(body, "name")
    capacity = helpers.as_int(body, "room_capacity_seats", min_value=1)
    tz = helpers.as_str(body, "timezone", required=False, default="America/Chicago")
    rec = models.make_studio(name, capacity, tz)
    db.studios[rec["id"]] = rec
    return object_response(models.serialize_studio(rec), 201)


@bp.get("/studio-ops/studios/<sid>")
def get_studio(sid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "Customer", "PlatformAdmin")
    rec = db.studios.get(sid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Studio not found")
    return object_response(models.serialize_studio(rec), 200)


@bp.get("/studio-ops/studios")
def list_studios():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "Customer", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    status = request.args.get("status")
    rows = list(db.studios.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_studio(r) for r in page],
                          limit, offset, total, 200)


@bp.post("/studio-ops/studios/<sid>/close")
def close_studio(sid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    rec = db.studios.get(sid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Studio not found")
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Studio is not ACTIVE")
    rec["status"] = "CLOSED"
    models.touch(rec)
    return object_response(models.serialize_studio(rec), 200)
