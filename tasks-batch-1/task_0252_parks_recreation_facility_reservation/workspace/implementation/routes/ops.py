"""Test-driving + ops endpoints: clock, sweep, no-show injection (PRD §3.10/§3.1)."""
from flask import Blueprint

import clock
import errors
import serializers
from clock import now as clock_now
from db import db, touch
from helpers import parse_body, require_fields, require_int, parse_dt
from middleware import get_identity, require_roles
from response import success
from services import calculations as calc

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    body = parse_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    clock.set_current(dt)
    from db import iso
    return success({"current_utc": iso(dt)})


@bp.post("/_ops/sweep")
def ops_sweep():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    now = clock_now()

    expired = 0
    for coi in db.insurance_certificates.values():
        if coi["status"] == "ACTIVE" and coi["expiry_date"] <= now:
            coi["status"] = "EXPIRED"
            touch(coi)
            expired += 1

    recomputed = 0
    for patron in db.patrons.values():
        new_standing = calc.patron_standing(patron["no_show_strikes"])
        if patron["standing"] != new_standing:
            patron["standing"] = new_standing
            touch(patron)
        recomputed += 1

    return success({"expired_coi_count": expired, "recomputed_patron_count": recomputed})


@bp.post("/_inject/no_show_strikes")
def inject_no_show_strikes():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    body = parse_body()
    require_fields(body, ["patron_id", "strikes"])
    patron = db.patrons.get(body["patron_id"])
    if patron is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")
    strikes = require_int(body, "strikes", minimum=0)
    patron["no_show_strikes"] = strikes
    patron["standing"] = calc.patron_standing(strikes)
    touch(patron)
    return success(serializers.patron(patron))
