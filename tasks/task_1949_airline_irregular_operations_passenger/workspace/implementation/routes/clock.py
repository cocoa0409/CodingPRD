"""POST /irops/_clock/set_current_utc — logical clock test-driving."""

from flask import Blueprint

import errors
from db import db, iso
from middleware import authenticate, require_role
from response import success_object
from validators import get_json_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/irops/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_role(caller, ["OpsAdmin"])
    body = get_json_body()
    to = req_datetime(body, "to_iso8601")
    db.clock = to
    return success_object({"current_utc": iso(db.clock)}, 200)
