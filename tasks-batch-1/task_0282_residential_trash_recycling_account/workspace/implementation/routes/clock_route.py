"""Test-driving clock endpoint (PRD §3.13)."""
from flask import Blueprint, request

import clock
from response import ok
from routes.helpers import gate
from services import validate as V
from services.billing import advance_clock_transitions
from util import format_ts

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    gate({"Dispatcher"})
    body = V.get_body(request)
    to = V.require_dt(body, "to_iso8601")
    clock.set_now(to)
    advanced = advance_clock_transitions()
    return ok({
        "current_utc": format_ts(clock.now()),
        "accounts_advanced": advanced,
    })
