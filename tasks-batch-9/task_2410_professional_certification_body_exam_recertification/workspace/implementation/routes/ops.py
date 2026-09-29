"""Test-driving capabilities: the logical clock and the maintenance run.

PRD 2.4 / 3.13.  Setting the clock is deliberately inert -- it mutates no stored
record -- and every time-driven transition is materialised only by the run.
"""

from flask import Blueprint

from db import DB
from dispatch import api
from middleware import (
    EVERY_AUTHENTICATED_ROLE,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_bool,
    peek_body,
    req_ts,
)
from response import object_response
from services import maintenance

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@api
def set_clock():
    authenticate(EVERY_AUTHENTICATED_ROLE)
    body = ensure_body(peek_body())
    instant = req_ts(body, "current_utc")
    DB.clock = instant
    return object_response({"current_utc": body["current_utc"]})


@bp.post("/recertification-runs")
@api
def recertification_run():
    authenticate([ROLE_PROGRAM_ADMIN])
    body = ensure_body(peek_body())
    dry_run = opt_bool(body, "dry_run", default=False)
    return object_response(maintenance.run(commit=not dry_run))
