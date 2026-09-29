"""The logical clock (PRD 2.5)."""
from flask import Blueprint

import db as store
from middleware import authorize
from response import ok
from validation import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@authorize("PlatformAdmin")
def set_current_utc():
    data = body()
    _raw, parsed = req_dt(data, "current_utc")
    store.db.clock = parsed
    return ok({})
