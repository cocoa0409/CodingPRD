"""The logical clock (PRD 2.4)."""

from flask import Blueprint

import db
import middleware as mw
import response
import shape
from db import store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    mw.require_roles(mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    current_utc = shape.req_datetime(payload, "current_utc")
    store.current_utc = current_utc
    return response.ok({"current_utc": db.clock_instant()})
