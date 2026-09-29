"""The logical clock control surface (§2.5)."""

from flask import Blueprint

import validation
from constants import API_PREFIX
from db import db, parse_dt
from middleware import require
from response import object_response

bp = Blueprint("clock", __name__, url_prefix=API_PREFIX)


@bp.post("/_clock/set_current_utc")
@require()
def set_current_utc():
    data = validation.body()
    raw = validation.get_string(data, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        validation.bad("Field 'to_iso8601' must be an ISO 8601 instant.")
    db.current_utc = parsed
    return object_response({})
