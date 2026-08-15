"""Logical clock endpoints."""
from flask import Blueprint

import store
import clock
from auth import authenticate, authorize
from errors import ERR_INVALID_REQUEST, raise_err
from util import body_json, req_str, parse_iso_datetime, success_object, bump, fmt_ts
from services import lot_service, hedge_service

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()

    to_iso8601 = req_str(body, "to_iso8601")
    dt = parse_iso_datetime(to_iso8601)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO-8601 datetime")

    clock.set_current(dt)
    current_date = clock.today()

    # Reconciliation events:

    # 1. Clear due health withdrawals
    for he in store.health_events.values():
        if he["status"] == "WITHDRAWAL_ACTIVE" and he["withdrawal_end_date"] <= current_date:
            he["status"] = "CLEARED"
            bump(he)

    # 2. Close ration assignments whose end_date is reached
    for ra in store.ration_assignments.values():
        if ra["status"] == "ACTIVE" and ra["end_date"] <= current_date:
            ra["status"] = "CLOSED"
            bump(ra)

    # 3. Expire hedge positions whose contract month has begun
    hedge_service.expire_hedges_for_clock_advance()

    # 4. Recompute provisional COG for non-terminal lots
    for lot in store.lots.values():
        if lot["status"] not in ("SETTLED",):
            lot_service.recompute_provisional_cog(lot)

    return success_object({"current_utc": fmt_ts(clock.now())})
