"""The logical programme clock (PRD 2.5).  Setting it mutates no entity."""
from flask import Blueprint

from auth import authorize
from envelope import object_response
from store import store
from validate import body, get_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("PlatformAdmin")
    data = body()
    _raw, instant = get_datetime(data, "to_iso8601")
    store.clock = instant
    return object_response({})
