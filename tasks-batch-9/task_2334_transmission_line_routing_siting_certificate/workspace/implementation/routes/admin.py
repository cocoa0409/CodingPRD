"""Administrative test-driving capability: the logical clock (PRD §2.6)."""

from flask import Blueprint

import response as resp
from db import store
from middleware import ALL_ROLES, endpoint
from validation import get_body, req_dt

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc():
    body = get_body()
    store.set_clock(req_dt(body, "current_utc"))
    return resp.empty_ok()
