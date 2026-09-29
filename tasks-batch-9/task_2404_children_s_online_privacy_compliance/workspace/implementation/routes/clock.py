"""Logical clock control (PRD §2.4)."""
from flask import Blueprint

from constants import ROLE_COMPLIANCE_OFFICER
from db import db
from middleware import authenticate, body, req_datetime
from response import ok
from timeutil import iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def set_current_utc():
    data = body()
    # Clock-dependent conclusions (safe_harbor_status, compliance_posture) are
    # derived on read, so moving the clock recomputes them for every service.
    db.current_utc = req_datetime(data, "to_iso8601")
    return ok({"current_utc": iso(db.current_utc)})
