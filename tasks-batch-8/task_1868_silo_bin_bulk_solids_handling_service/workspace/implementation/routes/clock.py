"""Logical clock test-driving endpoint."""
from flask import Blueprint

from db import store, parse_iso, iso_utc
from middleware import require_auth, require_role
from response import success_object
from services.validate import get_json_body, reject_unknown_fields, require_fields, as_iso8601

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    to = as_iso8601(body["to_iso8601"], "to_iso8601")

    require_role(ctx, {"ServiceManager"})

    store.logical_clock = parse_iso(to)
    return success_object({"current_utc": iso_utc(store.logical_clock)})
