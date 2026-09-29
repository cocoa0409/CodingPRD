"""The logical production clock (PRD 2.5)."""

from flask import Blueprint

from auth import ALL_PRODUCTION_ROLES, authenticate
from envelope import respond_object
from store import clock_set, iso
from validation import field_instant, json_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ALL_PRODUCTION_ROLES)
    body = json_body()
    to_iso8601 = field_instant(body, "to_iso8601")
    clock_set(to_iso8601)
    return respond_object({"current_utc": iso(to_iso8601)})
