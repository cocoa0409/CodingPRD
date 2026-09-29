"""The logical clock (PRD 2.5)."""

from flask import Blueprint

import db
import middleware
import response
import shape

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require(*middleware.ALL_STAFF)
    body = shape.body()
    target = shape.req_timestamp(body, "to_iso8601")
    db.set_clock(target)
    return response.object_response({"current_utc": db.iso(target)}, 200)
