"""Production runs: the aggregate hoist-window sweep and the panel reserve."""

from flask import Blueprint

import db
import response
from db import store, touch
from errors import (
    ERR_GROUND_CONTROL_DEFECT_OPEN,
    ERR_HOIST_CAPACITY_EXCEEDED,
    ERR_HOIST_UNAVAILABLE,
    ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
    ERR_PANEL_INVALID_STATE,
    ERR_PANEL_RESERVE_EXCEEDED,
    ERR_RUN_INVALID_STATE,
    ERR_STALE_MINE_VERSION,
    fail,
)
from middleware import auth
from services import calc, cascade, derive, serialize
from util import D, ZERO, body, filter_str, number, require, window

bp = Blueprint("runs", __name__)

RESERVE_STATUSES = ("SCHEDULED", "HELD", "HOISTED", "CLOSED")


def _reserve_committed(panel_id, exclude_run_id=None):
    total = ZERO
    for run in derive.runs_of_panel(panel_id):
        if exclude_run_id is not None and run["id"] == exclude_run_id:
            continue
        if run["status"] in RESERVE_STATUSES:
            total += D(run["planned_tons"])
    return total


def _check_capacity(mine, start, end, rate, exclude_run_id=None):
    peers = [r for r in derive.scheduled_runs_of_mine(mine["id"])
             if r["id"] != exclude_run_id]
    capacity = calc.mine_hourly_capacity(mine)
    peak = calc.peak_rate_in_window(start, end, rate, peers)
    if peak > capacity:
        fail(ERR_HOIST_CAPACITY_EXCEEDED,
             "peak concurrent rate %s exceeds the mine's hourly capacity %s"
             % (peak, capacity))


def _check_reserve(panel, planned_tons, exclude_run_id=None):
    committed = _reserve_committed(panel["id"], exclude_run_id) + D(planned_tons)
    if committed > D(panel["recoverable_tons"]):
        fail(ERR_PANEL_RESERVE_EXCEEDED,
             "committed tonnage %s exceeds the panel's recoverable_tons %s"
             % (committed, panel["recoverable_tons"]))


@bp.post("/salt/production-runs")
@auth("MinePlanner")
def create_run():
    payload = body()
    require(payload, ["mine_id", "panel_id", "planned_tons", "hoist_window_start",
                      "hoist_window_end", "expected_mine_version"])
    planned_tons = number(payload, "planned_tons", gt=0)
    start, end = window(payload, "hoist_window_start", "hoist_window_end")

    mine = derive.get_mine(payload["mine_id"])
    panel = derive.get_panel(payload["panel_id"])

    if payload["expected_mine_version"] != mine["version"]:
        fail(ERR_STALE_MINE_VERSION,
             "expected_mine_version %s does not match the mine's current version %s"
             % (payload["expected_mine_version"], mine["version"]))

    if panel["status"] != "PRODUCING":
        fail(ERR_PANEL_INVALID_STATE,
             "the target panel must be PRODUCING to host a run")
    if mine["compliance_state"] == "WITHDRAWAL_ORDER":
        fail(ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, "the mine is under a withdrawal order")
    if mine["hoist_state"] == "HOIST_DOWN":
        fail(ERR_HOIST_UNAVAILABLE, "the mine's shaft is down")
    if panel["open_defect"]:
        fail(ERR_GROUND_CONTROL_DEFECT_OPEN,
             "the panel carries an open ground-control defect")

    rate = calc.planned_rate(planned_tons, start, end)
    _check_capacity(mine, start, end, rate)
    _check_reserve(panel, planned_tons)

    run = db.stamp()
    run.update({
        "mine_id": mine["id"],
        "panel_id": panel["id"],
        "planned_tons": planned_tons,
        "hoist_window_start": start,
        "hoist_window_end": end,
        "planned_tons_per_hour": rate,
        "hoisted_tons": ZERO,
        "status": "SCHEDULED",
        "held_reason": None,
    })
    store.runs[run["id"]] = run
    touch(mine)
    return response.created(serialize.run_json(run))


@bp.get("/salt/production-runs/<run_id>")
@auth()
def read_run(run_id):
    return response.ok(serialize.run_json(derive.get_run(run_id)))


@bp.get("/salt/production-runs")
@auth()
def list_runs():
    rows = list(store.runs.values())
    for name in ("mine_id", "panel_id", "status", "held_reason"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.run_json)


@bp.post("/salt/production-runs/<run_id>/hoist")
@auth("MinePlanner")
def hoist_run(run_id):
    payload = body()
    require(payload, ["hoisted_tons"])
    hoisted = number(payload, "hoisted_tons", minv=0)

    run = derive.get_run(run_id)
    mine = derive.get_mine(run["mine_id"])
    panel = derive.get_panel(run["panel_id"])

    if run["status"] != "SCHEDULED":
        fail(ERR_RUN_INVALID_STATE,
             "run status %s does not admit a hoist" % run["status"])
    if mine["compliance_state"] == "WITHDRAWAL_ORDER":
        fail(ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, "the mine is under a withdrawal order")
    if mine["hoist_state"] == "HOIST_DOWN":
        fail(ERR_HOIST_UNAVAILABLE, "the mine's shaft is down")
    if panel["status"] != "PRODUCING":
        fail(ERR_PANEL_INVALID_STATE, "the panel must be PRODUCING to hoist")

    mined = derive.panel_mined_tons(panel["id"])
    if mined + D(hoisted) > D(panel["recoverable_tons"]):
        fail(ERR_PANEL_RESERVE_EXCEEDED,
             "mined tonnage %s plus %s exceeds the panel's recoverable_tons %s"
             % (mined, hoisted, panel["recoverable_tons"]))

    run["status"] = "HOISTED"
    run["hoisted_tons"] = hoisted
    touch(run)
    touch(panel)
    touch(mine)

    if derive.panel_mined_tons(panel["id"]) >= D(panel["recoverable_tons"]):
        cascade.terminate_panel(mine, panel, "DEPLETED", bump_mine=False)
    return response.ok(serialize.run_json(run))


@bp.post("/salt/production-runs/<run_id>/close")
@auth("MinePlanner")
def close_run(run_id):
    run = derive.get_run(run_id)
    if run["status"] != "HOISTED":
        fail(ERR_RUN_INVALID_STATE,
             "run status %s does not admit a close" % run["status"])
    if derive.run_open_batch_count(run["id"]) != 0:
        fail(ERR_RUN_INVALID_STATE,
             "the run still has pending treatment batches")
    run["status"] = "CLOSED"
    touch(run)
    return response.ok(serialize.run_json(run))


@bp.post("/salt/production-runs/<run_id>/reinstate")
@auth("MinePlanner")
def reinstate_run(run_id):
    run = derive.get_run(run_id)
    mine = derive.get_mine(run["mine_id"])
    panel = derive.get_panel(run["panel_id"])

    if run["status"] != "HELD":
        fail(ERR_RUN_INVALID_STATE,
             "run status %s does not admit a reinstatement" % run["status"])
    if mine["compliance_state"] == "WITHDRAWAL_ORDER":
        fail(ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, "the mine is under a withdrawal order")
    if mine["hoist_state"] == "HOIST_DOWN":
        fail(ERR_HOIST_UNAVAILABLE, "the mine's shaft is down")
    if panel["open_defect"]:
        fail(ERR_GROUND_CONTROL_DEFECT_OPEN,
             "the panel carries an open ground-control defect")
    if panel["status"] != "PRODUCING":
        fail(ERR_PANEL_INVALID_STATE,
             "the panel must be PRODUCING to host a reinstated run")

    _check_capacity(mine, run["hoist_window_start"], run["hoist_window_end"],
                    run["planned_tons_per_hour"], exclude_run_id=run["id"])
    _check_reserve(panel, run["planned_tons"], exclude_run_id=run["id"])

    run["status"] = "SCHEDULED"
    run["held_reason"] = None
    touch(run)
    touch(mine)
    return response.ok(serialize.run_json(run))
