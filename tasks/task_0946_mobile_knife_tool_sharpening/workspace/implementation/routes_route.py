"""Van route planning: runs, stops, dispatch, spill and reschedule."""

from flask import Blueprint

import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import (
    ARRIVAL_WINDOW_MINUTES,
    DEFAULT_DAY_WINDOW_END,
    DEFAULT_DAY_WINDOW_START,
    DRIVE_BUFFER_MINUTES_PER_STOP,
    RETURN_LEG_BUFFER_MINUTES,
    RUN_STATUSES,
    SPILL_MAX_HOPS,
    STOP_STATUSES,
    ZONE_CODES,
)
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("route", __name__)

RUN_SPEC = ladder.Spec(
    required=[
        ("van_id", "string"),
        ("technician_id", "string"),
        ("run_date", "string"),
        ("zone_code", "string"),
    ],
    optional=[
        ("service_minute_budget", "integer"),
        ("stop_cap", "integer"),
        ("day_window_start", "string"),
        ("day_window_end", "string"),
    ],
    enums={"zone_code": ZONE_CODES},
    ranges={"service_minute_budget": (1, None), "stop_cap": (1, None)},
    dates=["run_date"],
    times=["day_window_start", "day_window_end"],
)

STOP_SPEC = ladder.Spec(
    required=[
        ("service_request_id", "string"),
        ("sequence", "integer"),
        ("arrival_window_start", "string"),
        ("expected_route_run_version", "integer"),
    ],
    ranges={"sequence": (1, None)},
    times=["arrival_window_start"],
)


def _run_account(stop_or_request):
    return db.accounts.get(stop_or_request["account_id"]) if stop_or_request else None


def _parent_run(stop):
    return db.route_runs.get(stop["route_run_id"])


# ---------------------------------------------------------------------------
# POST /sharpening/route-runs
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-runs", methods=["POST"])
def create_run():
    ctx = ladder.begin("Dispatcher")
    RUN_SPEC.validate(ctx.body)
    van = ladder.must_exist(db.vans, ctx.body["van_id"], "Van")
    ladder.must_exist(db.technicians, ctx.body["technician_id"], "Technician")
    run_date = clockmod.parse_date(ctx.body["run_date"])
    # Rung 31.
    if run_date < clockmod.today():
        raise ApiError("ERR_DATE_IN_PAST")
    row = stamp_new(
        {
            "van_id": van["id"],
            "technician_id": ctx.body["technician_id"],
            "run_date": run_date,
            "zone_code": ctx.body["zone_code"],
            "service_minute_budget": ctx.body.get(
                "service_minute_budget", van["default_service_minute_budget"]
            ),
            "stop_cap": ctx.body.get("stop_cap", van["default_stop_cap"]),
            "day_window_start": clockmod.parse_hhmm(
                ctx.body.get("day_window_start", DEFAULT_DAY_WINDOW_START)
            ),
            "day_window_end": clockmod.parse_hhmm(
                ctx.body.get("day_window_end", DEFAULT_DAY_WINDOW_END)
            ),
            "status": "PLANNED",
            "committed_minutes_final": None,
        }
    )
    db.route_runs[row["id"]] = row
    return envelope.created(ser.route_run(row))


@bp.route("/sharpening/route-runs/<id>", methods=["GET"])
def get_run(id):
    ctx = ladder.begin("Dispatcher", "PlatformAdmin", "Technician")
    row = ladder.must_exist(db.route_runs, id, "RouteRun")
    services.acting_technician(ctx)
    return envelope.ok(ser.route_run(row))


@bp.route("/sharpening/route-runs", methods=["GET"])
def list_runs():
    ctx = ladder.begin("Dispatcher", "PlatformAdmin", "Technician")
    ladder.check_query_enums(
        ctx.query, {"zone_code": ZONE_CODES, "status": RUN_STATUSES}
    )
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.route_runs.values())
    for field in ("van_id", "technician_id", "zone_code", "status"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    run_date = ctx.query.get("run_date")
    if run_date is not None:
        rows = [r for r in rows if clockmod.render_date(r["run_date"]) == run_date]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.route_run(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/route-runs/{id}/stops
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-runs/<id>/stops", methods=["POST"])
def add_stop(id):
    ctx = ladder.begin("Dispatcher")
    run = ladder.must_exist(db.route_runs, id, "RouteRun")
    STOP_SPEC.validate(ctx.body)
    # Rung 9 -- resolved leniently so a suspended account outranks an unknown FK.
    loose_request = db.service_requests.get(ctx.body["service_request_id"])
    services.account_active(_run_account(loose_request))
    request_row = ladder.must_exist(
        db.service_requests, ctx.body["service_request_id"], "ServiceRequest"
    )
    account = db.accounts.get(request_row["account_id"])
    # Rung 11.
    services.credit_gate(account)
    # Rung 12.
    services.occ(ctx.body, "expected_route_run_version", run)
    # Rung 13 / 14 on the service request's fulfilment axis.
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["status"] != "SUBMITTED" or request_row["channel"] not in (
        "VAN_ROUTE",
        "REWORK",
    ):
        raise ApiError("ERR_INVALID_STATE", "The request cannot take a route stop.")
    # Rung 15.
    if run["status"] != "PLANNED":
        raise ApiError("ERR_RUN_NOT_MUTABLE")
    # Rung 27.
    if account is None or account["zone_code"] != run["zone_code"]:
        raise ApiError("ERR_STOP_ACCOUNT_MISMATCH")
    # Rung 33.
    start = clockmod.parse_hhmm(ctx.body["arrival_window_start"])
    end = start + ARRIVAL_WINDOW_MINUTES
    if start < run["day_window_start"] or end > run["day_window_end"]:
        raise ApiError("ERR_WINDOW_OUT_OF_DAY")
    # Rung 34.
    for other in ser.run_active_stops(run["id"]):
        if services.windows_overlap(
            start, end, other["arrival_window_start"], other["arrival_window_end"]
        ):
            raise ApiError("ERR_WINDOW_OVERLAP")
    # Rung 52.
    active = ser.run_active_stops(run["id"])
    if len(active) + 1 > run["stop_cap"]:
        raise ApiError("ERR_STOP_CAP_EXCEEDED")
    # Rung 53.
    incoming = sum(
        i["service_minutes_declared"]
        for i in ser.request_items(request_row["id"])
        if i["service_status"] not in ("RETURNED_UNSERVICED", "ABANDONED")
    )
    provisional = (
        ser.run_booked_minutes(run["id"])
        + incoming
        + DRIVE_BUFFER_MINUTES_PER_STOP * (len(active) + 1)
    )
    if provisional > run["service_minute_budget"]:
        raise ApiError("ERR_RUN_MINUTES_EXCEEDED")

    stop = stamp_new(
        {
            "route_run_id": run["id"],
            "service_request_id": request_row["id"],
            "account_id": request_row["account_id"],
            "spilled_from_route_run_id": None,
            "sequence": ctx.body["sequence"],
            "arrival_window_start": start,
            "arrival_window_end": end,
            "spill_hop_count": 0,
            "status": "SCHEDULED",
        }
    )
    db.route_stops[stop["id"]] = stop
    request_row["status"] = "SCHEDULED"
    touch(request_row)
    touch(run)
    return envelope.created(ser.route_stop(stop))


# ---------------------------------------------------------------------------
# Stop reads
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-stops/<id>", methods=["GET"])
def get_stop(id):
    ctx = ladder.begin("Dispatcher", "PlatformAdmin", "Technician")
    row = ladder.must_exist(db.route_stops, id, "RouteStop")
    services.acting_technician(ctx)
    return envelope.ok(ser.route_stop(row))


@bp.route("/sharpening/route-stops", methods=["GET"])
def list_stops():
    ctx = ladder.begin("Dispatcher", "PlatformAdmin", "Technician")
    ladder.check_query_enums(ctx.query, {"status": STOP_STATUSES})
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.route_stops.values())
    for field in (
        "route_run_id",
        "service_request_id",
        "account_id",
        "spilled_from_route_run_id",
        "status",
    ):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.route_stop(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# DELETE /sharpening/route-stops/{id}
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-stops/<id>", methods=["DELETE"])
def delete_stop(id):
    ladder.begin("Dispatcher")
    stop = ladder.must_exist(db.route_stops, id, "RouteStop")
    services.account_active(db.accounts.get(stop["account_id"]))
    if stop["status"] in ("SERVICED", "SKIPPED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "The stop is not SCHEDULED.")
    run = _parent_run(stop)
    if run is None or run["status"] != "PLANNED":
        raise ApiError("ERR_RUN_NOT_MUTABLE")

    request_row = db.service_requests.get(stop["service_request_id"])
    del db.route_stops[stop["id"]]
    if request_row is not None and request_row["status"] == "SCHEDULED":
        request_row["status"] = "SUBMITTED"
        touch(request_row)
    touch(run)
    return envelope.no_content()


# ---------------------------------------------------------------------------
# POST /sharpening/route-stops/{id}/spill
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-stops/<id>/spill", methods=["POST"])
def spill_stop(id):
    ladder.begin("Dispatcher")
    stop = ladder.must_exist(db.route_stops, id, "RouteStop")
    services.account_active(db.accounts.get(stop["account_id"]))
    if stop["status"] in ("SERVICED", "SKIPPED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "The stop is not SCHEDULED.")
    run = _parent_run(stop)
    if run is None or run["status"] not in ("PLANNED", "DISPATCHED"):
        raise ApiError("ERR_RUN_NOT_MUTABLE")
    # Rung 42.
    if stop["spill_hop_count"] + 1 > SPILL_MAX_HOPS:
        raise ApiError("ERR_SPILL_LIMIT_REACHED")

    stop["spill_hop_count"] += 1
    stop["spilled_from_route_run_id"] = stop["route_run_id"]
    stop["status"] = "SPILLED"
    touch(stop)
    request_row = db.service_requests.get(stop["service_request_id"])
    if request_row is not None and request_row["status"] == "SCHEDULED":
        request_row["status"] = "SUBMITTED"
        touch(request_row)
    return envelope.ok(ser.route_stop(stop))


# ---------------------------------------------------------------------------
# POST /sharpening/route-stops/{id}/reschedule
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-stops/<id>/reschedule", methods=["POST"])
def reschedule_stop(id):
    ladder.begin("Dispatcher")
    stop = ladder.must_exist(db.route_stops, id, "RouteStop")
    account = db.accounts.get(stop["account_id"])
    services.account_active(account)
    if stop["status"] in ("SERVICED", "SKIPPED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if stop["status"] != "SPILLED":
        raise ApiError("ERR_INVALID_STATE", "The stop is not SPILLED.")
    run = _parent_run(stop)
    if run is None or run["status"] != "PLANNED":
        raise ApiError("ERR_RUN_NOT_MUTABLE")
    # Rung 50 -- the receiving-run pool; the selector also applies the zone,
    # cap and minute filters of rungs 27, 52 and 53.
    receiving = services.select_receiving_run(stop)
    # Rung 27 against the chosen run.
    if account is None or account["zone_code"] != receiving["zone_code"]:
        raise ApiError("ERR_STOP_ACCOUNT_MISMATCH")
    # Rung 33 -- placement window, which fails when the day has no free slot.
    start = services.next_free_window(receiving)
    end = start + ARRIVAL_WINDOW_MINUTES
    # Rung 52 / 53 against the chosen run.
    active = ser.run_active_stops(receiving["id"])
    if len(active) + 1 > receiving["stop_cap"]:
        raise ApiError("ERR_STOP_CAP_EXCEEDED")
    minutes = ser.stop_service_minutes(stop)
    provisional = (
        ser.run_booked_minutes(receiving["id"])
        + minutes
        + DRIVE_BUFFER_MINUTES_PER_STOP * (len(active) + 1)
    )
    if provisional > receiving["service_minute_budget"]:
        raise ApiError("ERR_RUN_MINUTES_EXCEEDED")

    stop["route_run_id"] = receiving["id"]
    stop["sequence"] = services.next_sequence(receiving)
    stop["arrival_window_start"] = start
    stop["arrival_window_end"] = end
    stop["status"] = "SCHEDULED"
    touch(stop)
    request_row = db.service_requests.get(stop["service_request_id"])
    if request_row is not None and request_row["status"] == "SUBMITTED":
        request_row["status"] = "SCHEDULED"
        touch(request_row)
    touch(receiving)
    return envelope.ok(ser.route_stop(stop))


# ---------------------------------------------------------------------------
# POST /sharpening/route-stops/{id}/arrive
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-stops/<id>/arrive", methods=["POST"])
def arrive_stop(id):
    ctx = ladder.begin("Technician")
    stop = ladder.must_exist(db.route_stops, id, "RouteStop")
    run = _parent_run(stop)
    services.own_run_technician(ctx, run)
    services.account_active(db.accounts.get(stop["account_id"]))
    if stop["status"] in ("SERVICED", "SKIPPED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "The stop is not SCHEDULED.")
    if run is None or run["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        raise ApiError("ERR_RUN_NOT_MUTABLE")

    stop["status"] = "ARRIVED"
    touch(stop)
    if run["status"] == "DISPATCHED":
        run["status"] = "IN_PROGRESS"
        touch(run)
    return envelope.ok(ser.route_stop(stop))


# ---------------------------------------------------------------------------
# POST /sharpening/route-runs/{id}/dispatch
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-runs/<id>/dispatch", methods=["POST"])
def dispatch_run(id):
    ladder.begin("Dispatcher")
    run = ladder.must_exist(db.route_runs, id, "RouteRun")
    if run["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "The run is not PLANNED.")
    active = ser.run_active_stops(run["id"])
    if len(active) < 1:
        raise ApiError("ERR_INVALID_STATE", "The run carries no stop.")
    # Rung 31.
    if run["run_date"] < clockmod.today():
        raise ApiError("ERR_DATE_IN_PAST")

    excluded = set()

    def committed():
        stops = [s for s in active if s["id"] not in excluded]
        return (
            sum(ser.stop_service_minutes(s, assessed=True) for s in stops)
            + DRIVE_BUFFER_MINUTES_PER_STOP * len(stops)
            + RETURN_LEG_BUFFER_MINUTES
        )

    plan = []
    while committed() > run["service_minute_budget"]:
        candidates = [
            s for s in active if s["id"] not in excluded and s["status"] == "SCHEDULED"
        ]
        if not candidates:
            break
        victim = max(candidates, key=lambda s: s["sequence"])
        # Rung 42 -- the whole dispatch fails and nothing is changed.
        if victim["spill_hop_count"] + 1 > SPILL_MAX_HOPS:
            raise ApiError("ERR_SPILL_LIMIT_REACHED")
        excluded.add(victim["id"])
        plan.append(victim)

    for victim in plan:
        victim["spill_hop_count"] += 1
        victim["spilled_from_route_run_id"] = victim["route_run_id"]
        victim["status"] = "SPILLED"
        touch(victim)
        request_row = db.service_requests.get(victim["service_request_id"])
        if request_row is not None and request_row["status"] == "SCHEDULED":
            request_row["status"] = "SUBMITTED"
            touch(request_row)

    run["committed_minutes_final"] = committed()
    run["status"] = "DISPATCHED"
    touch(run)
    return envelope.ok(ser.route_run(run))


# ---------------------------------------------------------------------------
# POST /sharpening/route-runs/{id}/complete
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-runs/<id>/complete", methods=["POST"])
def complete_run(id):
    ladder.begin("Dispatcher")
    run = ladder.must_exist(db.route_runs, id, "RouteRun")
    if run["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "The run is not IN_PROGRESS.")
    for stop in db.route_stops.values():
        if stop["route_run_id"] == run["id"] and stop["status"] in (
            "SCHEDULED",
            "ARRIVED",
        ):
            raise ApiError("ERR_INVALID_STATE", "A stop is still open on this run.")
    run["status"] = "COMPLETED"
    touch(run)
    return envelope.ok(ser.route_run(run))


# ---------------------------------------------------------------------------
# POST /sharpening/route-runs/{id}/cancel
# ---------------------------------------------------------------------------
@bp.route("/sharpening/route-runs/<id>/cancel", methods=["POST"])
def cancel_run(id):
    ladder.begin("Dispatcher")
    run = ladder.must_exist(db.route_runs, id, "RouteRun")
    if run["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "The run is not PLANNED.")
    for stop in db.route_stops.values():
        if stop["route_run_id"] != run["id"] or stop["status"] != "SCHEDULED":
            continue
        stop["status"] = "CANCELLED"
        touch(stop)
        request_row = db.service_requests.get(stop["service_request_id"])
        if request_row is not None and request_row["status"] == "SCHEDULED":
            request_row["status"] = "SUBMITTED"
            touch(request_row)
    run["status"] = "CANCELLED"
    touch(run)
    return envelope.ok(ser.route_run(run))
