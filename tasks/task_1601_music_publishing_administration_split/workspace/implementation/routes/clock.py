from flask import Blueprint

import db
from middleware import auth_context, require_roles
from response import success
from validators import body_json, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
def set_current_utc():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    to = req_dt(body, "to_iso8601")
    db.set_clock(to)
    return success({"current_utc": db.iso(to)})
