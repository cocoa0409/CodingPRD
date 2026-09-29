"""Union labor calls: dispatch, check-in, band billing and cancellation (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles
from services import calc, state
from validation import json_body, parse_dt, require_row

bp = Blueprint("labor", __name__)
store = db.store

TERMINAL = ("COMPLETED", "NO_SHOW", "CANCELLED")
LIVE_STATUSES = ("REQUESTED", "DISPATCHED", "ON_SITE")


def _booth_exhibitor(call):
    if not call:
        return None
    booth = store.booths.get(call["booth_id"])
    return booth["exhibitor_id"] if booth else None


@bp.post("/labor-calls")
def create_call():
    require_roles("Exhibitor", "ShowOperations")
    body = json_body()
    peeked = store.booths.get(body.peek_str("booth_id"))
    own_exhibitor(peeked["exhibitor_id"] if peeked else None)

    booth_id = body.string("booth_id")
    jurisdiction_id = body.string("jurisdiction_id")
    scheduled_start = body.datetime_str("scheduled_start")
    scheduled_end = body.datetime_str("scheduled_end")
    crew_size = body.integer("crew_size")
    service_order_id = body.string("service_order_id", required=False, default=None)
    self_install = body.boolean("self_install_requested", required=False, default=False)

    booth = require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")
    jurisdiction = require_row(store.jurisdictions, jurisdiction_id,
                               "ERR_JURISDICTION_NOT_FOUND", "Union jurisdiction")
    if service_order_id is not None:
        require_row(store.service_orders, service_order_id,
                    "ERR_SERVICE_ORDER_NOT_FOUND", "Service order")

    show = store.shows.get(booth["show_id"])
    guards.booth_not_frozen(booth)

    if self_install and not jurisdiction["exhibitor_self_install_allowed"]:
        raise ApiError("ERR_UNION_JURISDICTION_REQUIRED",
                       "This jurisdiction does not permit exhibitor self-install")

    start = parse_dt(scheduled_start)
    end = parse_dt(scheduled_end)
    if show is not None:
        envelope_start = parse_dt(show["move_in_start"])
        envelope_end = parse_dt(show["move_out_end"])
    else:
        envelope_start = envelope_end = None
    if start >= end or (envelope_start is not None
                        and (start < envelope_start or end > envelope_end)):
        raise ApiError("ERR_LABOR_WINDOW_OUTSIDE_SHOW",
                       "The crew window is inverted or falls outside the show envelope")

    buffer_minutes = timedelta(minutes=int(jurisdiction["turnaround_buffer_minutes"]))
    for existing in store.labor_calls.values():
        if existing["booth_id"] != booth_id or \
                existing["jurisdiction_id"] != jurisdiction_id:
            continue
        if existing["status"] not in LIVE_STATUSES:
            continue
        existing_start = parse_dt(existing["scheduled_start"])
        existing_end = parse_dt(existing["scheduled_end"])
        if start < existing_end + buffer_minutes and existing_start < end + buffer_minutes:
            raise ApiError("ERR_LABOR_CALL_OVERLAP",
                           "A live call on this crew resource sits inside the buffer")

    if show is not None and jurisdiction["venue_id"] != show["venue_id"]:
        raise ApiError("ERR_JURISDICTION_VENUE_MISMATCH",
                       "The jurisdiction belongs to a different venue")

    if crew_size < 1 or crew_size > int(jurisdiction["crew_max_size"]):
        raise ApiError("ERR_CREW_SIZE_LIMIT", "crew_size is outside the jurisdiction bounds")

    scheduled_hours = calc.hours_2dp(
        calc.dec((end - start).total_seconds()) / calc.dec(3600))

    call = {
        "id": db.new_id(),
        "booth_id": booth_id,
        "jurisdiction_id": jurisdiction_id,
        "service_order_id": service_order_id,
        "trade": jurisdiction["trade"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "crew_size": crew_size,
        "self_install_requested": self_install,
        "actual_start": None,
        "actual_end": None,
        "scheduled_hours": scheduled_hours,
        "billed_hours": None,
        "st_hours": None,
        "ot_hours": None,
        "dt_hours": None,
        "labor_charge_cents": None,
        "status": "REQUESTED",
    }
    db.stamp_common(call)
    store.labor_calls[call["id"]] = call
    return response.created(call)


@bp.get("/labor-calls/<call_id>")
def get_call(call_id):
    require_roles(ANY_ROLE)
    call = store.labor_calls.get(call_id)
    own_exhibitor(_booth_exhibitor(call))
    call = require_row(store.labor_calls, call_id, "ERR_LABOR_CALL_NOT_FOUND",
                       "Labor call")
    return response.ok(call)


@bp.get("/labor-calls")
def list_calls():
    require_roles(ANY_ROLE)
    rows = list(store.labor_calls.values())
    rows = response.filter_rows(rows, "booth_id", "jurisdiction_id", "service_order_id",
                                "status")
    return response.listing(rows)


@bp.post("/labor-calls/<call_id>/dispatch")
def dispatch(call_id):
    require_roles("LaborSupervisor")
    json_body()
    call = require_row(store.labor_calls, call_id, "ERR_LABOR_CALL_NOT_FOUND",
                       "Labor call")
    booth = store.booths.get(call["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None

    guards.transition(call["status"], TERMINAL, ("REQUESTED",))
    guards.show_accepting(show, ("MOVE_IN", "ON_SITE", "MOVE_OUT"))
    guards.booth_open(booth)

    call["status"] = "DISPATCHED"
    db.touch(call)
    if show is not None:
        state.recompute_show_aggregates(show)
    return response.ok(call)


@bp.post("/labor-calls/<call_id>/check-in")
def check_in(call_id):
    require_roles("LaborSupervisor")
    body = json_body()
    actual_start = body.datetime_str("actual_start")
    call = require_row(store.labor_calls, call_id, "ERR_LABOR_CALL_NOT_FOUND",
                       "Labor call")
    booth = store.booths.get(call["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None

    guards.transition(call["status"], TERMINAL, ("DISPATCHED",))

    if show is not None:
        started = parse_dt(actual_start)
        if started < parse_dt(show["move_in_start"]) or \
                started > parse_dt(show["move_out_end"]):
            raise ApiError("ERR_LABOR_WINDOW_OUTSIDE_SHOW",
                           "actual_start falls outside the show envelope")

    call["actual_start"] = actual_start
    call["status"] = "ON_SITE"
    db.touch(call)
    if show is not None:
        state.recompute_show_aggregates(show)
    return response.ok(call)


@bp.post("/labor-calls/<call_id>/completion")
def completion(call_id):
    require_roles("LaborSupervisor")
    body = json_body()
    outcome = body.enum("outcome", ("COMPLETED", "NO_SHOW"))
    actual_end = body.datetime_str("actual_end", required=False, default=None)
    if outcome == "COMPLETED" and actual_end is None:
        raise ApiError("ERR_INVALID_REQUEST", "actual_end is required on a worked call")

    call = require_row(store.labor_calls, call_id, "ERR_LABOR_CALL_NOT_FOUND",
                       "Labor call")
    booth = store.booths.get(call["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None
    jurisdiction = store.jurisdictions.get(call["jurisdiction_id"])
    venue = store.venues.get(show["venue_id"]) if show else None

    if outcome == "COMPLETED":
        guards.transition(call["status"], TERMINAL, ("ON_SITE",))
        started = parse_dt(call["actual_start"])
        ended = parse_dt(actual_end)
        if ended <= started:
            raise ApiError("ERR_LABOR_WINDOW_OUTSIDE_SHOW",
                           "actual_end must be later than actual_start")
        billing = calc.labor_billing(
            started, ended, jurisdiction["min_call_hours"], call["crew_size"],
            jurisdiction["straight_time_rate_cents_per_hour"],
            jurisdiction["overtime_multiplier"], jurisdiction["doubletime_multiplier"],
            (venue or {}).get("straight_time_start_hhmm", "08:00"),
            (venue or {}).get("straight_time_end_hhmm", "16:30"))
        call["actual_end"] = actual_end
        call.update(billing)
        call["status"] = "COMPLETED"
        db.touch(call)
    else:
        guards.transition(call["status"], TERMINAL, ("DISPATCHED",))
        call["labor_charge_cents"] = calc.no_show_charge(
            call["crew_size"], jurisdiction["min_call_hours"],
            jurisdiction["straight_time_rate_cents_per_hour"])
        call["status"] = "NO_SHOW"
        db.touch(call)

    if show is not None:
        state.recompute_show_aggregates(show)
    if outcome == "NO_SHOW" and booth is not None:
        state.refresh_booth(booth)
    return response.ok(call)


@bp.post("/labor-calls/<call_id>/cancel")
def cancel(call_id):
    require_roles("LaborSupervisor", "ShowOperations")
    body = json_body()
    body.string("reason", required=False, default=None)
    call = require_row(store.labor_calls, call_id, "ERR_LABOR_CALL_NOT_FOUND",
                       "Labor call")
    booth = store.booths.get(call["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None

    guards.transition(call["status"], TERMINAL, ("REQUESTED", "DISPATCHED"))

    call["status"] = "CANCELLED"
    db.touch(call)
    if show is not None:
        state.recompute_show_aggregates(show)
    return response.ok(call)
