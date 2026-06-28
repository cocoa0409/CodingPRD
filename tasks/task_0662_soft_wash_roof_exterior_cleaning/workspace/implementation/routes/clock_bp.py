from flask import Blueprint

import clock
from middleware import get_identity, require_role
from response import success
from services.common import get_body, require_fields, parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    # PRD §2.2: for 2xx responses with no data, data is an empty object.
    return success({}, 200)
