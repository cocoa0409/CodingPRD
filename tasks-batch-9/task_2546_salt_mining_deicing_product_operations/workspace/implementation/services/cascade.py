"""Multi-hop cascades: capacity re-fit, panel suspension, panel termination."""

import db
from db import touch
from services import calc, derive
from util import D


def hold_run(run, reason):
    run["status"] = "HELD"
    run["held_reason"] = reason
    touch(run)


def void_run(run):
    run["status"] = "VOIDED"
    run["held_reason"] = None
    touch(run)


def recompute_mine_capacity(mine, bump=True):
    derive.refresh_mine_capacity(mine)
    if bump:
        touch(mine)


def capacity_refit(mine):
    """Hold SCHEDULED runs until the aggregate concurrent rate fits capacity.

    The offending run whose window starts latest is held first; ties on start
    are broken by created_at descending.
    """
    capacity = calc.mine_hourly_capacity(mine)
    while True:
        runs = derive.scheduled_runs_of_mine(mine["id"])
        if not runs:
            return
        segments = calc.over_capacity_segments(runs, capacity)
        if not segments:
            return
        offenders = [r for r in runs
                     if any(calc.run_overlaps(r, a, b) for (a, b) in segments)]
        if not offenders:
            return
        offenders.sort(key=lambda r: (r["hoist_window_start"], r["created_at"],
                                      r["_seq"]), reverse=True)
        hold_run(offenders[0], "CAPACITY")


def hold_all_scheduled(mine, reason):
    for run in db.by_seq(derive.scheduled_runs_of_mine(mine["id"])):
        hold_run(run, reason)


def tighten_shaft(mine):
    """Hop 2 of the suspension cascade."""
    producing = derive.mine_producing_panel_count(mine["id"])
    current = mine["hoist_state"]
    if current == "HOIST_DOWN":
        target = "HOIST_DOWN"
    elif producing == 0:
        target = "HOIST_DOWN"
    elif current == "HOIST_AVAILABLE":
        target = "HOIST_DERATED"
    else:
        target = "HOIST_DOWN"
    if target != current:
        mine["hoist_state"] = target
    recompute_mine_capacity(mine)


def panel_left_production(mine, panel):
    """Hops 2 through 4: shaft tightens, runs are held, open tonnage re-derives."""
    tighten_shaft(mine)
    for run in db.by_seq(derive.runs_of_panel(panel["id"])):
        if run["status"] == "SCHEDULED":
            hold_run(run, "GROUND_CONTROL")
    capacity_refit(mine)


def terminate_panel(mine, panel, status, bump_mine=True):
    """DEPLETED or ABANDONED: void live runs and freeze the reserve."""
    panel["status"] = status
    touch(panel)
    for run in db.by_seq(derive.runs_of_panel(panel["id"])):
        if run["status"] in ("SCHEDULED", "HELD"):
            void_run(run)
    if bump_mine:
        touch(mine)
