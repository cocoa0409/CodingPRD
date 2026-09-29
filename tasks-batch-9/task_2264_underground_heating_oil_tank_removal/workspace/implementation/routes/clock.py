"""The logical site clock (§2.5)."""

from flask import Blueprint

from db import db, iso
from middleware import authenticate, body, req_datetime
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("ComplianceOfficer", "ProjectCoordinator"))
    payload = body()
    moment = req_datetime(payload, "to_iso8601")
    db.set_clock(moment)
    # Setting the clock mutates no entity and fires no cascade.
    return object_response({"current_utc": iso(moment)})
