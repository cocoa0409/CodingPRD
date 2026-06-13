"""Test-driving logical-clock endpoint (PRD 2.10)."""
from flask import Blueprint

from clock import clock
from middleware import get_principal, require_role
from reqs import get_json_body, req_str
from response import object_response
from util import parse_iso, iso_now

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    body = get_json_body()
    to_iso8601 = req_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    clock.set(dt)
    return object_response({"current_utc": iso_now(dt)})
