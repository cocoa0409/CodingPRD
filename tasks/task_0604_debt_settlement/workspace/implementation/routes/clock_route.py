from flask import Blueprint

from errors import fail, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from clock import clock, parse_iso8601
from routes.helpers import get_body, require_fields

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_clock():
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    if dt is None:
        fail(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO8601 instant")
    clock.set(dt)
    return success({})
