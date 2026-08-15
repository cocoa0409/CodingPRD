"""Test-driving logical clock (PRD §2.4)."""

from flask import Blueprint

from db import store, fmt_ts
from middleware import require_roles, ROLE_INTEGRATOR_ADMIN
from response import success_object
from util import get_body, req, as_datetime

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    to = as_datetime(req(body, "to_iso8601"), "to_iso8601")
    now = store.clock.set(to)
    return success_object({"current_utc": fmt_ts(now)}, 200)
