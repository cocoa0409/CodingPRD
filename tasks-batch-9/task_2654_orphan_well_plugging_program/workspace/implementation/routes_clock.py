"""Logical regulatory clock control (PRD 2.5)."""
from flask import Blueprint

import calc
import validate as v
from auth import STAFF_ROLES, endpoint
from envelope import empty_response
from store import set_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(STAFF_ROLES)
def set_current_utc():
    data = v.body()
    to_iso8601 = v.datetime_field(data, "to_iso8601")
    set_clock(to_iso8601)
    # Advancing the clock expires every lapsed funding source.
    calc.expire_funding_sources()
    return empty_response(200)
