"""The server's logical clock (PRD 2.4)."""

from flask import Blueprint

import config
from envelope import ok
from ladder import auth, field, raw_body, validate
from store import store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth([config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [field("to_iso8601", "datetime", required=True)])
    store.set_clock(data["to_iso8601"])
    return ok({"current_utc": store.now()})
