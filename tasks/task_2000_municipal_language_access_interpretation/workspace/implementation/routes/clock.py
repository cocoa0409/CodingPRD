"""Logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import get_body, reject_unknown_fields, req_datetime_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"to_iso8601"})
    to_iso8601 = req_datetime_str(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})
