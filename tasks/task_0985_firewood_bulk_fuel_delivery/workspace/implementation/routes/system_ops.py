"""Test-driving endpoints: logical clock and season-end sweep (PRD §2.5, §3.9)."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint

import errors
from clock import clock
from db import db
from middleware import require_roles
from response import success_object
from services.domain import day_before_cutoff, run_season_sweep
from util import get_json_body, require_int, require_str

bp = Blueprint("system_ops", __name__)


def _apply_scheduled_actions(prev_dt, new_dt):
    """Apply time-triggered transitions when the clock advances from prev_dt to new_dt.

    - Season-end sweep: crossing Apr 1 00:00:00 of any year sweeps ACTIVE
      subscriptions whose season closes that year (season_year = crossing_year - 1).
    - Window auto-lock: crossing a window's day-before cutoff locks OPEN windows.
    """
    transitioned = []
    if new_dt > prev_dt:
        # Season-end sweep for every Apr 1 boundary crossed
        year = prev_dt.year
        while True:
            boundary = datetime(year, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
            if boundary <= prev_dt:
                year += 1
                continue
            if prev_dt < boundary <= new_dt:
                transitioned.extend(run_season_sweep(year - 1))
                year += 1
                continue
            break
        # Window auto-lock
        for w in db.delivery_windows.values():
            if w["status"] != "OPEN":
                continue
            cutoff = day_before_cutoff(w)
            if prev_dt < cutoff <= new_dt:
                # Locking requires all SCHEDULED orders PAID; the auto-lock at
                # cutoff applies regardless — but per state machine the
                # precondition is that SCHEDULED orders are PAID. We lock only
                # when the precondition holds, mirroring the manual lock.
                ok = True
                for o in db.orders.values():
                    if o.get("delivery_window_id") == w["id"] and o["fulfillment_status"] == "SCHEDULED":
                        if o["payment_status"] != "PAID":
                            ok = False
                            break
                if ok:
                    w["status"] = "LOCKED"
                    from util import touch
                    touch(w)
    return transitioned


@bp.post("/api/v1/_clock/set_current_utc")
def set_clock():
    require_roles("OperationsManager")
    body = get_json_body()
    to_iso8601 = require_str(body, "to_iso8601")
    prev = clock.now()
    try:
        new_dt = clock.set(to_iso8601)
    except Exception:
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    _apply_scheduled_actions(prev, new_dt)
    return success_object({"current_utc": clock.now_iso()})


@bp.post("/api/v1/_sweep/season_end")
def sweep_season_end():
    require_roles("OperationsManager")
    body = get_json_body()
    season_year = require_int(body, "season_year")
    transitioned = run_season_sweep(season_year)
    return success_object({"transitioned_subscription_ids": transitioned})
