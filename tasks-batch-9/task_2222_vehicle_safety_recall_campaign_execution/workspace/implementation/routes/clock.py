"""Logical clock control - all roles, mutates no entity."""
from flask import Blueprint

import validators as v
from auth import ALL_ROLES, require_roles
from db import fmt_instant, store
from response import single

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles(*ALL_ROLES)
def set_current_utc():
    payload = v.body()
    _, moment = v.req_instant_str(payload, "to_iso8601")
    store.clock = moment
    return single({"current_utc": fmt_instant(moment)})
