"""Season endpoints: create, read, advance-posture, run-ops (PRD 3.1, 3.8)."""
from flask import Blueprint

from authz import require_role
from db import store
from errors import malformed, posture_guard, invalid_state
from helpers import (body, get_or_404, new_record, req_enum, req_field,
                     req_int, touch)
from respond import success
from serialize import season_out
from services import POSTURES, run_ops_sweeps
from timeutil import date_as_instant, parse_date, parse_datetime

bp = Blueprint("seasons", __name__)


def _req_datetime(data, name):
    raw = req_field(data, name)
    try:
        return parse_datetime(raw)
    except ValueError:
        raise malformed("Field %s must be an ISO 8601 datetime" % name)


def _req_date(data, name):
    raw = req_field(data, name)
    try:
        return parse_date(raw)
    except ValueError:
        raise malformed("Field %s must be an ISO date (YYYY-MM-DD)" % name)


@bp.post("/api/seasons")
def create_season():
    require_role("Owner")
    data = body()
    rec = new_record({
        "year": req_int(data, "year"),
        "booking_open_at": _req_datetime(data, "booking_open_at"),
        "booking_close_at": _req_datetime(data, "booking_close_at"),
        "harvest_window_start": _req_date(data, "harvest_window_start"),
        "harvest_window_end": _req_date(data, "harvest_window_end"),
        "shipping_window_start": _req_datetime(data, "shipping_window_start"),
        "shipping_window_end": _req_datetime(data, "shipping_window_end"),
        "posture": "PLANNING",
        "ops_run_index": 0,
    })
    store.seasons[rec["id"]] = rec
    return success(season_out(rec), status=201)


@bp.get("/api/seasons/<sid>")
def get_season(sid):
    require_role("Owner", "FarmManager", "WholesaleBuyer", "CrewLead")
    return success(season_out(get_or_404(store.seasons, sid)))


@bp.post("/api/seasons/<sid>/advance-posture")
def advance_posture(sid):
    require_role("Owner")
    season = get_or_404(store.seasons, sid)
    data = body()
    target = req_enum(data, "target_posture", POSTURES)

    # State validity (priority 6): posture walks forward exactly one step;
    # CLOSED is terminal.
    cur = POSTURES.index(season["posture"])
    if season["posture"] == "CLOSED" or POSTURES.index(target) != cur + 1:
        raise invalid_state("Posture must advance exactly one step forward")

    # Guard conditions (priority 8), per the Season state machine.
    clk = store.clock
    if target == "BOOKING":
        if clk < season["booking_open_at"]:
            raise posture_guard("The booking window has not opened yet")
    elif target == "HARVEST":
        if clk < date_as_instant(season["harvest_window_start"]):
            raise posture_guard("The harvest window has not started yet")
        if any(o["season_id"] == sid and o["status"] == "DRAFT"
               for o in store.orders.values()):
            raise posture_guard("Draft wholesale orders remain in this season")
    elif target == "SHIPPING":
        season_order_ids = {o["id"] for o in store.orders.values()
                            if o["season_id"] == sid}
        if any(a["order_id"] in season_order_ids
               and a["status"] in ("RESERVED", "CUT")
               for a in store.allocations.values()):
            raise posture_guard("Allocations remain RESERVED or CUT in this season")
    elif target == "SETTLEMENT":
        if any(ld["season_id"] == sid and ld["status"] == "BUILDING"
               for ld in store.loads.values()):
            raise posture_guard("Loads remain BUILDING in this season")
    elif target == "CLOSED":
        if any(c["season_id"] == sid
               and c["status"] in ("DELIVERED", "SETTLING", "DISPUTED")
               for c in store.consignments.values()):
            raise posture_guard("Consignments remain unsettled in this season")

    season["posture"] = target
    touch(season)
    return success(season_out(season))


@bp.post("/api/seasons/<sid>/run-ops")
def run_ops(sid):
    require_role("Owner")
    season = get_or_404(store.seasons, sid)
    run_ops_sweeps(season)
    return success(season_out(season))
