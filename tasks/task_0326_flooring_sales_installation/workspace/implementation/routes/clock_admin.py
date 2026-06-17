"""Test-driving clock endpoint: POST /_clock/set_current_utc."""
from flask import Blueprint

import clock
from errors import err
from middleware import require_roles
from response import ok
from services.helpers import body, require_fields

bp = Blueprint("clock_admin", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("Admin")
def set_clock():
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        dt = clock.parse(data["to_iso8601"])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant.")
    clock.set_now(dt)
    return ok({})
