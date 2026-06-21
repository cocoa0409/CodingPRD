"""Test-only clock endpoint (PRD §3.11). Drives the missed-bus window."""

from flask import Blueprint

from db import DB
from middleware import authenticate, require_role
from response import ok
from services import validate as v
from services.calc import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()
    to_iso8601 = v.require_str(body, "to_iso8601")
    DB.current_utc = parse_iso(to_iso8601)
    return ok({}, 200)
