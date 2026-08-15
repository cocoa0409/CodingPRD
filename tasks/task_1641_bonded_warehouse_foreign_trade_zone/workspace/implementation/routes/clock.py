"""Test-driving logical clock endpoint (SCAFFOLD 1.5, PRD 2.5)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import get_body, reject_unknown_fields, req_datetime

bp = Blueprint("clock", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorized(ALL_ROLES)
    body = get_body()
    reject_unknown_fields(body, {"to_iso8601"})
    to_iso8601 = req_datetime(body, "to_iso8601")
    dt = CLOCK.set(to_iso8601)
    from util import fmt_dt
    return success_object({"current_utc": fmt_dt(dt)})
