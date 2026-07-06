"""Guest endpoints (PRD §3.5)."""
from flask import Blueprint
import errors
import validate
import serialize
from db import db
from middleware import require_auth
from records import new_record, touch
from response import object_response
from util import parse_datetime

bp = Blueprint("guests", __name__)


@bp.post("/guests")
def create():
    require_auth({"Operator", "Guest"})
    body = validate.get_json_body()
    validate.require_fields(body, ["full_name", "birth_date"])
    full_name = validate.require_str(body, "full_name")
    birth_date = body["birth_date"]
    if not isinstance(birth_date, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "birth_date must be a string")
    if parse_datetime(birth_date) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "birth_date is not a valid ISO 8601 date")
    rec = new_record({
        "full_name": full_name,
        "birth_date": birth_date,
        "age_verified": False,
        "waiver_signed": False,
    })
    db.guests[rec["id"]] = rec
    return object_response(serialize.guest(rec), status=201)


@bp.get("/guests/<gid>")
def get_guest(gid):
    require_auth({"Operator", "Guide", "Guest"})
    rec = db.guests.get(gid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Guest not found")
    return object_response(serialize.guest(rec), status=200)


@bp.post("/guests/<gid>/sign-waiver")
def sign_waiver(gid):
    require_auth({"Operator", "Guest"})
    rec = db.guests.get(gid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Guest not found")
    rec["waiver_signed"] = True
    touch(rec)
    return object_response(serialize.guest(rec), status=200)
