"""Studio registry endpoints."""
from flask import Blueprint

import errors
from db import DB
from middleware import auth, json_body
from response import ok
from services import base_record, lazy_read_tick, studio_json

bp = Blueprint("studios", __name__)


@bp.post("/studios")
def create_studio():
    auth(["CastingDirector"])
    body = json_body()
    for field in ("studio_name", "location", "has_directed_patch", "hourly_rate_cents", "operating_tz"):
        if body.get(field) is None:
            raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(body["studio_name"], str) or not isinstance(body["location"], str):
        raise errors.invalid_request("studio_name and location must be strings")
    if not isinstance(body["has_directed_patch"], bool):
        raise errors.invalid_request("has_directed_patch must be a boolean")
    if not isinstance(body["hourly_rate_cents"], int) or isinstance(body["hourly_rate_cents"], bool):
        raise errors.invalid_request("hourly_rate_cents must be an integer")
    if not isinstance(body["operating_tz"], str):
        raise errors.invalid_request("operating_tz must be an IANA timezone string")
    rec = base_record()
    rec.update({
        "studio_name": body["studio_name"],
        "location": body["location"],
        "has_directed_patch": body["has_directed_patch"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "operating_tz": body["operating_tz"],
        "status": "OPEN",
    })
    DB["studios"][rec["id"]] = rec
    return ok(studio_json(rec), 201)


@bp.get("/studios/<sid>")
def get_studio(sid):
    auth(["CastingDirector", "Client", "StudioEngineer"])
    lazy_read_tick()
    rec = DB["studios"].get(sid)
    if rec is None:
        raise errors.not_found("Studio not found")
    return ok(studio_json(rec))
