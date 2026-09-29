"""PRD 2.5 the server-controlled logical clock."""
from flask import Blueprint

import auth
import clock
import response
import validators as v

bp = Blueprint("clock_api", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require_auth(("NetworkAdmin",))
    body = v.get_body()
    v.reject_unversioned(body)
    current_utc = v.req_instant(body, "current_utc")
    clock.set_now(current_utc, clock.parse_instant(current_utc))
    return response.ok({"current_utc": current_utc})
