"""Applicator endpoints + test-driving clock (PRD §3.10)."""
from flask import Blueprint

import clock
import db
import lookups
import serializers
from errors import err
from helpers import get_json_body, optional_bool, require_str
from middleware import require_roles
from response import object_response
from timeutil import iso_now, parse_iso

bp = Blueprint("applicators", __name__)


@bp.post("/applicators")
@require_roles("FarmManager")
def create_applicator():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    license_no = require_str(body, "license_no")
    certified = optional_bool(body, "certified", True)

    rec = db.new_entity(
        {"full_name": full_name, "license_no": license_no, "certified": certified}
    )
    db.applicators[rec["id"]] = rec
    return object_response(serializers.applicator(rec), 201)


@bp.get("/applicators/<aid>")
@require_roles("FarmManager", "Agronomist", "Applicator")
def get_applicator(aid):
    rec = lookups.applicator(aid)
    return object_response(serializers.applicator(rec))


@bp.post("/_clock/set")
@require_roles("FarmManager")
def set_clock():
    body = get_json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string.")
    dt = parse_iso(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    clock.set_clock(dt)
    return object_response({"current_utc": iso_now(dt)})
