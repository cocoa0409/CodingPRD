"""Test-driving endpoint for the logical UTC clock (PRD section 2.4)."""
from flask import Blueprint

from db import store
from middleware import PA, endpoint
from response import iso_ms, object_response
from shapes import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint([PA])
def set_current_utc():
    b = body()
    to_iso8601 = req_dt(b, "to_iso8601")
    # No entity writes: every derived read simply re-evaluates against the new
    # instant on its next serialization.
    store.clock = to_iso8601
    return object_response({"current_utc": iso_ms(store.clock)})
