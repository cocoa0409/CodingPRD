from flask import Blueprint

import store
from common import authorize, get_json, need, as_str
from envelope import object_response
from errors import err
from timeutil import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(["Manager"])
    body = get_json()
    to_iso = as_str(need(body, "to_iso8601"), "to_iso8601")
    try:
        parse_dt(to_iso)
    except ValueError:
        raise err("ERR_VALIDATION", "to_iso8601 is not a valid ISO 8601 instant")
    store.set_clock(to_iso)
    return object_response({}, 200)
