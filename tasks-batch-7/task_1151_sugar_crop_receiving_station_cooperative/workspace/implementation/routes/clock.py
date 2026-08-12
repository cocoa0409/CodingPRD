from flask import Blueprint

import db
import response
import serializers
from middleware import require_roles
from routes._common import as_dt, body, req_field

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles(["COOP_ADMIN"])
    data = body()
    to_iso = req_field(data, "to_iso8601")
    dt = as_dt(to_iso, "to_iso8601")
    db.set_clock(to_iso)
    return response.success({"current_utc": db.format_iso(dt)}, 200)
