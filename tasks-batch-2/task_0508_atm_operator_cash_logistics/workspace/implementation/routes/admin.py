"""Test-driving routes: logical clock + monthly_wd_count seeder (PRD §3.12)."""
from flask import Blueprint

import lookups
import serialize
import validate
import services.clock_svc as clock_svc
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_object
from util import iso_now, parse_iso

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    to_iso = validate.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    new_dt = clock_svc.set_clock(store, dt)
    return ok_object(store.clock, {"current_utc": iso_now(new_dt)})


@bp.route("/_inject/atm_monthly_wd_count", methods=["POST"])
def inject_monthly_wd_count():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    atm_id = validate.require_str(body, "atm_id")
    count = validate.require_int(body, "monthly_wd_count")
    atm = lookups.atm(store, atm_id)
    # Sets only monthly_wd_count; creates no transactions, touches no other field.
    atm["monthly_wd_count"] = count
    store.touch(atm)
    return ok_object(store.clock, serialize.atm(store, atm))
