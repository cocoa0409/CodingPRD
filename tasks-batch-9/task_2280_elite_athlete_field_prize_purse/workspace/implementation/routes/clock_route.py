"""The logical clock control surface (PRD 2.4)."""
from flask import Blueprint

from clock import clock, fmt_dt, parse_dt
from middleware import authenticate
from response import object_response
from validators import get_body, rstr

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((
        "ElitesDirector",
        "TechnicalOfficial",
        "FinanceOfficer",
        "AntiDopingLiaison",
        "SanctioningBody",
    ))
    body = get_body()
    target = parse_dt(rstr(body, "to_iso8601"), "to_iso8601")
    clock.set(target)
    return object_response({"current_utc": fmt_dt(clock.now())})
