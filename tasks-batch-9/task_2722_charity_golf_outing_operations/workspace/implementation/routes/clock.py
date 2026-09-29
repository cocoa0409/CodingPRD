"""The logical clock control endpoint (PRD section 2.4)."""

from flask import Blueprint

import store
import validate
from auth import STAFF_ROLES, auth
from envelope import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(STAFF_ROLES)
    body = validate.body()
    validate.only_fields(body, ("current_utc",))
    current_utc = validate.req_ts(body, "current_utc")
    store.set_clock(current_utc)
    return ok({"current_utc": current_utc})
