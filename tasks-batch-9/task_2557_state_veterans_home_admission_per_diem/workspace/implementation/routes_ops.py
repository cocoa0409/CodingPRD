"""Test-driving endpoints: the logical clock and the nightly operations
checkpoint."""
from flask import Blueprint

import services
from common import f_date, f_datetime, f_id, fail, guard, json_body, object_response
from store import clock_date, now_iso, parse_date, set_clock, store

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guard("StateProgramAdmin")
    body = json_body()
    instant = f_datetime(body, "to_iso8601")
    set_clock(instant)
    return object_response({"current_utc": now_iso()})


@bp.post("/_ops/census-run")
def census_run():
    user_id, _role = guard("StateProgramAdmin")
    body = json_body()
    through_date = f_date(body, "through_date")
    home_id = f_id(body, "veterans_home_id", required=False)

    home = None
    if home_id is not None:
        home = store.homes.get(home_id)
        if home is None:
            fail("ERR_HOME_NOT_FOUND", "No veterans home with id %s." % home_id)
    if parse_date(through_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "through_date may not lie in the future.")

    counters = services.census_run(through_date, home["id"] if home else None, user_id)
    return object_response(counters)
