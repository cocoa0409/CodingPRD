"""Logical clock test-driving capability (CorporateAdmin only)."""
from flask import Blueprint, Response

import db
from authz import require_roles
from validate import body_json, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(["CorporateAdmin"])
    data = body_json()
    to = req_dt(data, "to_iso8601")
    db.set_clock(to)
    # 204 No Content -- the clock advance mutates no entity.
    return Response(status=204)
