"""Logical clock endpoint: advance time and run the expiration sweep."""
from flask import Blueprint

from auth import require_roles, ROLE_RIGHTS_MANAGER, ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER
from domain import run_sweep
from errors import err, ERR_CLOCK_REGRESSION
from response import ok_object
from util import CLOCK, fmt_dt
from validate import field_dt, json_body

bp = Blueprint("clock", __name__)


@bp.route("/licensing/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(ROLE_RIGHTS_MANAGER, ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER)
    body = json_body(required=True)
    target = field_dt(body, "to_iso8601", required=True)
    if target < CLOCK.now():
        err(ERR_CLOCK_REGRESSION, "to_iso8601 is before the current logical clock")
    CLOCK.set(body["to_iso8601"])
    tallies = run_sweep(CLOCK.now())
    return ok_object(
        {
            "current_utc": fmt_dt(CLOCK.now()),
            "slots_expired": tallies["slots_expired"],
            "licenses_expired": tallies["licenses_expired"],
            "licenses_terminated": tallies["licenses_terminated"],
            "packages_expired": tallies["packages_expired"],
            "notices_executed": tallies["notices_executed"],
        }
    )
