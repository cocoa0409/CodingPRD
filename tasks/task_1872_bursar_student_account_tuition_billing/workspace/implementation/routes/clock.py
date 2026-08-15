from flask import Blueprint

from db import store, fmt_clock
from dates import parse_instant
from middleware import auth_context, require_roles
from response import success, json_body, req_field

bp = Blueprint("clock", __name__)


@bp.post("/bursar/_clock/set_current_utc")
def set_clock():
    auth = auth_context()
    require_roles(auth[1], "RegistrarStaff", "BursarStaff", "BursarManager")
    body = json_body()
    target = parse_instant(req_field(body, "to_iso8601"))
    store.clock = target
    return success({"current_utc": fmt_clock(store.clock)}, status=200)
