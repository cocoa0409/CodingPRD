from flask import Blueprint

from db import CLOCK, fmt_ts
from middleware import (
    as_datetime_str,
    authenticate,
    get_json_body,
    require_roles,
)
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    to_iso8601 = as_datetime_str(body, "to_iso8601")
    dt = CLOCK.set(to_iso8601)
    return success_object({"current_utc": fmt_ts(dt)}, status=200)
