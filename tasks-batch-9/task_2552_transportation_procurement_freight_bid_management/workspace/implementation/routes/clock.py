"""The logical procurement clock — PRD §2.5.  Uniquely among the endpoints in this
specification it does not require the user-context headers of §2.1."""
from flask import Blueprint

import responses
import store
import validators as v

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    payload = v.body()
    to_iso = v.dt_field(payload, "to_iso8601")
    store.set_clock(store.parse_dt(to_iso))
    return responses.empty(200)
