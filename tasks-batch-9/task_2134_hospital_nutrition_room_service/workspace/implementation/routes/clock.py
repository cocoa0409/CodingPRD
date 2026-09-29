"""The logical UTC clock capability (PRD section 2.4)."""

from flask import Blueprint

import api
import store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@api.require(*api.ALL_ROLES)
def set_current_utc():
    body = api.body()
    instant = api.req_dt(body, "to_iso8601")
    store.set_clock(instant)
    return api.ok({"current_utc": store.iso(store.now())})
