"""Test-driving logical clock endpoint (PRD §2.6)."""
from flask import Blueprint

import clock
import util
from middleware import get_context, require_roles
from response import success_object

bp = Blueprint("misc", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    data = util.body()
    util.require_fields(data, ["to_iso8601"])
    current = clock.set_current(data.get("to_iso8601"))
    return success_object({"current_utc": current}, 200)
