"""POST /_clock/set_current_utc — the one endpoint exempt from §2.1 headers."""

from flask import Blueprint

from core import body, clock, iso, req_datetime, respond_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body()
    moment = req_datetime(data, "current_utc")
    clock.set(moment)
    return respond_object({"current_utc": iso(moment)})
