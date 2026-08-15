"""Logical clock endpoints (PRD §2.4)."""

from flask import Blueprint

from db import CLOCK
from middleware import require_roles, json_body
from response import success_object
from services.common import require_string, parse_iso_datetime
from db import iso_ts

bp = Blueprint("clock", __name__)


@bp.route("/pdm/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("DataSteward")
    body = json_body()
    to_iso = require_string(body, "to_iso8601")
    dt = parse_iso_datetime(to_iso)
    CLOCK.set(dt)
    return success_object({"current_utc": iso_ts(CLOCK.now())})
