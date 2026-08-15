"""The test-driving logical clock (PRD §2.4). ExchangeAdmin only."""

from flask import Blueprint

from db import store, fmt_clock
from middleware import require_roles, ROLE_EXCHANGE_ADMIN
from response import success_object
from util import get_body, req_datetime
from services.core import run_clock_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles([ROLE_EXCHANGE_ADMIN])
    body = get_body()
    dt = req_datetime(body, "to_iso8601")
    old = store.clock.now()
    store.clock.set(dt)
    run_clock_sweeps(old, dt)
    return success_object({"current_utc": fmt_clock(store.clock.now())})
