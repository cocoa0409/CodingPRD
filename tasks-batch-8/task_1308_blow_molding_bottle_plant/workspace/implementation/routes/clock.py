from flask import Blueprint

from auth import authenticate, require_role
from envelope import success_object
from util import set_logical_clock, fmt_dt
from validate import get_body, check_fields

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {"to_iso8601": ("datetime", True)})
    set_logical_clock(body["to_iso8601"])
    return success_object({"current_utc": fmt_dt(body["to_iso8601"])})
