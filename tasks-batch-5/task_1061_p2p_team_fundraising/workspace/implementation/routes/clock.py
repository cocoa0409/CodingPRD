"""Test-driving logical clock (PRD 2.5)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    to_iso8601 = v.req_dt(body, "to_iso8601")
    db.set_clock(to_iso8601)
    return response.object_response({"current_utc": db.now_iso()})
