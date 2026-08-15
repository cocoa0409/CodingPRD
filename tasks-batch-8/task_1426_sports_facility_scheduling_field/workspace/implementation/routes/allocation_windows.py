"""Allocation window routes: create, read, open, close, run-allocation (PRD 3.4-3.5)."""

from flask import Blueprint

import errors
import util
import clock
from db import store, iso_from_dt
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("allocation_windows", __name__)


@bp.post("/allocation-windows")
def create_window():
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    season_code = util.require_str(body, "season_code")
    opens_at = util.require_iso(body, "opens_at")
    closes_at = util.require_iso(body, "closes_at")
    if closes_at <= opens_at:
        raise errors.invalid_request("closes_at must be strictly after opens_at")
    prime_cap = util.require_int(body, "prime_cap_hours_per_org", min_v=1)
    max_tourn = util.require_int(body, "max_tournament_days_per_org", min_v=0)

    window = util.new_entity({
        "season_code": season_code,
        "opens_at": iso_from_dt(opens_at),
        "closes_at": iso_from_dt(closes_at),
        "status": "SCHEDULED",
        "prime_cap_hours_per_org": prime_cap,
        "max_tournament_days_per_org": max_tourn,
    })
    store.allocation_windows[window["id"]] = window
    return success_object(window, 201)


@bp.get("/allocation-windows/<wid>")
def get_window(wid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_window(wid))


@bp.post("/allocation-windows/<wid>/open")
def open_window(wid):
    require_roles("AthleticsAdmin")
    window = core.get_window(wid)
    if window["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_INVALID_WINDOW_STATE,
                              "Window must be SCHEDULED to open", 409)
    opens_at = util.parse_iso(window["opens_at"], "opens_at")
    if clock.now() < opens_at:
        raise errors.ApiError(errors.ERR_WINDOW_NOT_YET_OPEN,
                              "Window may not open before opens_at", 409)
    window["status"] = "OPEN"
    util.touch(window)
    return success_object(window)


@bp.post("/allocation-windows/<wid>/close")
def close_window(wid):
    require_roles("AthleticsAdmin")
    window = core.get_window(wid)
    if window["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_INVALID_WINDOW_STATE,
                              "Window must be OPEN to close", 409)
    window["status"] = "CLOSED"
    util.touch(window)
    # Sweep SUBMITTED applications into UNDER_REVIEW in the same request.
    for a in sorted(store.permit_applications.values(), key=util.sort_key):
        if a["window_id"] == window["id"] and a["status"] == "SUBMITTED":
            a["status"] = "UNDER_REVIEW"
            util.touch(a)
    return success_object(window)


@bp.post("/allocation-windows/<wid>/run-allocation")
def run_allocation(wid):
    require_roles("AthleticsAdmin")
    window = core.get_window(wid)
    if window["status"] != "CLOSED":
        raise errors.ApiError(errors.ERR_INVALID_WINDOW_STATE,
                              "Window must be CLOSED to run allocation", 409)
    core.run_allocation(window)
    window["status"] = "ALLOCATED"
    util.touch(window)
    return success_object(window)
