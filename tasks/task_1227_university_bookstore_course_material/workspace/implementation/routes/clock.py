from flask import Blueprint

from db import store
from middleware import require_roles, body, get_dt
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/bookstore/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    data = body()
    store.clock = get_dt(data, "to_iso8601")
    return success({}, status=200, response_type="object")
