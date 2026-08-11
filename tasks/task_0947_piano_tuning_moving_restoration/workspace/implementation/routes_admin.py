"""The logical clock and the daily operations sweep (PRD 2.5, 3.4)."""

from flask import Blueprint, jsonify

import services
from core import CLOCK, LOCK, Ctx, fail, ok, parse_iso

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    with LOCK:
        ctx = Ctx(["PlatformAdmin"])
        body = ctx.read_body(["to_iso8601"])
        raw = body["to_iso8601"]
        dt = parse_iso(raw) if isinstance(raw, str) else None
        if dt is None:
            fail("ERR_VALIDATION", "to_iso8601 must be an ISO-8601 instant.")
        CLOCK.set(raw, dt)
        reevaluated = services.reevaluate_all_locations()
        payload, status = ok({"current_utc": CLOCK.raw,
                              "locations_reevaluated": reevaluated})
        return jsonify(payload), status


@bp.post("/_ops/daily-sweep")
def daily_sweep():
    with LOCK:
        ctx = Ctx(["PlatformAdmin"])
        ctx.read_body([])
        counts = services.daily_sweep()
        payload, status = ok(counts)
        return jsonify(payload), status
