"""The logical-clock control capability (PRD §2.4)."""

from flask import Blueprint

import clock
import middleware
from middleware import endpoint
from validation import parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdministrator"], body={"to_iso8601": {"type": "datetime", "required": True}})
def set_current_utc():
    clock.set_instant(parse_datetime(middleware.body()["to_iso8601"]))
    return middleware.empty()
