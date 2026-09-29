"""Test-driving surface: the server-side logical clock (PRD 2.4).

Before this endpoint is ever called the logical clock reads exactly
2026-08-01T00:00:00Z; it never falls back to wall-clock time.
"""

from flask import Blueprint

import db
from middleware import (FINANCE_CONTROLLER, PLAN_ADMIN, authenticate, get_body,
                        parse_timestamp)
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate([PLAN_ADMIN, FINANCE_CONTROLLER])
    body = get_body()
    db.set_clock(parse_timestamp(body, "current_utc"))
    return object_response({})
