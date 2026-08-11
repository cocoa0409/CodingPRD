"""The two administrative test-driving capabilities: the logical clock and the
hold sweep.  CARVE-OUT: rung 15 never applies to either."""

from flask import Blueprint

import config
from db import DB, touch
from ladder import endpoint
from response import ok
from services import capacity, cascade
from tsutil import gte, ts_input

bp = Blueprint("admin", __name__)

ADMIN = config.ROLE_ADMIN


@bp.post("/bakery/_clock/set_current_utc")
@endpoint(roles=[ADMIN])
def set_clock(ctx):
    raw = ctx.req_dt("to_iso8601")                      # rung 13
    previous = DB.clock
    # case B: the clock carries the caller's own string byte-verbatim, and every
    # instant derived from it renders in that same style.
    DB.clock = ts_input(raw)
    return ok({"current_utc": DB.clock.s, "previous_utc": previous.s})


@bp.post("/bakery/_holds/expire-due")
@endpoint(roles=[ADMIN])
def expire_due(ctx):
    fks = ctx.body_fks(optional=("offer_window_id",))   # rung 8
    scoped = fks.get("offer_window_id")
    now = ctx.now

    expired_orders = 0
    released_lines = 0
    released_units = 0
    touched = []
    for order in DB.values("orders"):
        if order.get("order_status") != "PENDING_HOLD":
            continue
        if scoped is not None and order.get("offer_window_id") != scoped["id"]:
            continue
        hold = order.get("hold_expires_at")
        if hold is None or not gte(now, hold):
            continue
        units, count = cascade.release_pending_lines(order, now)
        order["order_status"] = "EXPIRED_HOLD"
        order["hold_expires_at"] = None
        touch(order, now)
        expired_orders += 1
        released_lines += count
        released_units += units
        wid = order.get("offer_window_id")
        if wid not in touched:
            touched.append(wid)

    for wid in touched:
        capacity.sync(DB.get("offer_windows", wid), now, force_bump=True)

    posture = None
    if scoped is not None:
        capacity.store(scoped, now)
        posture = scoped.get("capacity_posture")
    elif touched:
        last = DB.get("offer_windows", touched[-1])
        posture = (last or {}).get("capacity_posture")
    else:
        windows = DB.values("offer_windows")
        if len(windows) == 1:
            capacity.store(windows[0], now)
            posture = windows[0].get("capacity_posture")
    return ok({
        "expired_order_count": expired_orders,
        "released_line_count": released_lines,
        "released_units": released_units,
        "capacity_posture": posture,
    })
