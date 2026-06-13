"""Test-driving clock route (PRD §2.10)."""

from flask import Blueprint

import db
from middleware import get_auth, require_role
from response import object_response
import validation as V

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    body = V.get_body()
    to_iso8601 = V.parse_dt(V.require(body, "to_iso8601"), "to_iso8601")
    db.set_clock(to_iso8601)
    return object_response({}, 200)
