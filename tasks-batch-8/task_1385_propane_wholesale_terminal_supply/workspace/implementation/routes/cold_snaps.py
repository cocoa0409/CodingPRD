"""Cold snap event + allocation run endpoints (SupplyPlanner)."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_state,
    err_window_invalid,
    err_cold_snap_already_active,
    err_terminal_not_curtailed,
    err_run_not_computed,
    err_stale_terminal_version,
)

bp = Blueprint("cold_snaps", __name__)

CS_READ_ROLES = ["SupplyPlanner", "SupplyAdmin", "Dispatcher", "CreditManager", "DealerUser"]
CS_WRITE_ROLES = ["SupplyPlanner"]
SEVERITIES = {"WATCH", "WARNING", "EMERGENCY"}
CS_STATES = {"DECLARED", "ACTIVE", "LIFTED"}
RUN_READ_ROLES = ["SupplyPlanner", "SupplyAdmin"]
RUN_STATES = {"OPEN", "COMPUTED", "RATIFIED", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# Cold snap events
# ---------------------------------------------------------------------------

@bp.route("/cold-snap-events", methods=["POST"])
def create_cold_snap():
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    severity = mw.req_enum(body, "severity", SEVERITIES)
    start_date = mw.req_date(body, "start_date")
    end_date = mw.req_date(body, "end_date")

    if terminal_id not in db.terminals:
        raise err_referenced_not_found("terminal_id does not resolve")
    if end_date < start_date:
        raise err_window_invalid("end_date < start_date")

    now = svc.stamp_now()
    e = {
        "id": db.new_id(),
        "terminal_id": terminal_id,
        "severity": severity,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DECLARED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.cold_snap_events[e["id"]] = e
    return resp.created(ser.serialize_cold_snap(e))


@bp.route("/cold-snap-events/<eid>", methods=["GET"])
def get_cold_snap(eid):
    caller = mw.authenticate()
    mw.authorize(caller, CS_READ_ROLES)
    e = db.cold_snap_events.get(eid)
    if e is None:
        raise err_not_found()
    return resp.ok(ser.serialize_cold_snap(e))


@bp.route("/cold-snap-events", methods=["GET"])
def list_cold_snaps():
    caller = mw.authenticate()
    mw.authorize(caller, CS_READ_ROLES)
    limit, offset = mw.pagination_params()
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum("status", CS_STATES)
    items = list(db.cold_snap_events.values())
    if terminal_id is not None:
        items = [e for e in items if e["terminal_id"] == terminal_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_cold_snap(e) for e in page], limit, offset, total)


@bp.route("/cold-snap-events/<eid>/activate", methods=["POST"])
def activate_cold_snap(eid):
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    e = db.cold_snap_events.get(eid)
    if e is None:
        raise err_not_found()
    if e["status"] != "DECLARED":
        raise err_invalid_state("Only a DECLARED cold snap can be activated")
    for other in db.cold_snap_events.values():
        if (
            other["id"] != e["id"]
            and other["terminal_id"] == e["terminal_id"]
            and other["status"] == "ACTIVE"
        ):
            raise err_cold_snap_already_active()
    terminal = db.terminals[e["terminal_id"]]
    e["status"] = "ACTIVE"
    svc.touch(e)
    svc.terminal_curtail(terminal)
    return resp.ok(ser.serialize_cold_snap(e))


@bp.route("/cold-snap-events/<eid>/lift", methods=["POST"])
def lift_cold_snap(eid):
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    e = db.cold_snap_events.get(eid)
    if e is None:
        raise err_not_found()
    if e["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE cold snap can be lifted")
    terminal = db.terminals[e["terminal_id"]]
    e["status"] = "LIFTED"
    svc.touch(e)
    svc.terminal_restore(terminal)
    return resp.ok(ser.serialize_cold_snap(e))


# ---------------------------------------------------------------------------
# Allocation runs
# ---------------------------------------------------------------------------

@bp.route("/allocation-runs", methods=["POST"])
def create_allocation_run():
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    expected_terminal_version = mw.req_int(body, "expected_terminal_version")

    terminal = db.terminals.get(terminal_id)
    if terminal is None:
        raise err_referenced_not_found("terminal_id does not resolve")

    if expected_terminal_version != terminal["version"]:
        raise err_stale_terminal_version()

    # supersede the terminal's existing OPEN/COMPUTED run
    for r in db.allocation_runs.values():
        if r["terminal_id"] == terminal_id and r["status"] in ("OPEN", "COMPUTED"):
            r["status"] = "SUPERSEDED"
            svc.touch(r)

    next_index = 1
    for r in db.allocation_runs.values():
        if r["terminal_id"] == terminal_id and r["run_index"] >= next_index:
            next_index = r["run_index"] + 1

    now = svc.stamp_now()
    r = {
        "id": db.new_id(),
        "terminal_id": terminal_id,
        "run_index": next_index,
        "status": "OPEN",
        "pool_gal": None,
        "results": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.allocation_runs[r["id"]] = r
    svc.touch(terminal)  # creating a run bumps Terminal.version
    return resp.created(ser.serialize_allocation_run(r))


@bp.route("/allocation-runs/<rid>", methods=["GET"])
def get_allocation_run(rid):
    caller = mw.authenticate()
    mw.authorize(caller, RUN_READ_ROLES)
    r = db.allocation_runs.get(rid)
    if r is None:
        raise err_not_found()
    return resp.ok(ser.serialize_allocation_run(r))


@bp.route("/allocation-runs", methods=["GET"])
def list_allocation_runs():
    caller = mw.authenticate()
    mw.authorize(caller, RUN_READ_ROLES)
    limit, offset = mw.pagination_params()
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum("status", RUN_STATES)
    items = list(db.allocation_runs.values())
    if terminal_id is not None:
        items = [r for r in items if r["terminal_id"] == terminal_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_allocation_run(r) for r in page], limit, offset, total)


@bp.route("/allocation-runs/<rid>/compute", methods=["POST"])
def compute_allocation_run(rid):
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    r = db.allocation_runs.get(rid)
    if r is None:
        raise err_not_found()
    if r["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN run can be computed")
    terminal = db.terminals[r["terminal_id"]]
    if terminal["allocation_posture"] != "CURTAILED":
        raise err_terminal_not_curtailed()
    svc.compute_waterfall(terminal, r)
    r["status"] = "COMPUTED"
    svc.touch(r)
    return resp.ok(ser.serialize_allocation_run(r))


@bp.route("/allocation-runs/<rid>/ratify", methods=["POST"])
def ratify_allocation_run(rid):
    caller = mw.authenticate()
    mw.authorize(caller, CS_WRITE_ROLES)
    r = db.allocation_runs.get(rid)
    if r is None:
        raise err_not_found()
    if r["status"] == "SUPERSEDED":
        raise err_invalid_state("A SUPERSEDED run rejects every action")
    if r["status"] != "COMPUTED":
        raise err_run_not_computed()
    for row in r["results"]:
        o = db.delivery_orders.get(row["order_id"])
        if o is None or o["fulfillment_status"] != "REQUESTED":
            continue
        if row["allocated_gal"] > 0:
            o["fulfillment_status"] = "ALLOCATED"
            o["allocated_gal"] = row["allocated_gal"]
            svc.touch(o)
            svc.restamp_provisional(o)
        else:
            o["fulfillment_status"] = "SHORTED"
            o["allocated_gal"] = 0
            o["provisional_total_cents"] = None
            svc.touch(o)
    r["status"] = "RATIFIED"
    svc.touch(r)
    return resp.ok(ser.serialize_allocation_run(r))
