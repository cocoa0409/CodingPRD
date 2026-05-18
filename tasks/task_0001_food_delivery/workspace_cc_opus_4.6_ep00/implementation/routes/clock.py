from flask import Blueprint, request
from middleware import check_role_permission
from response import success_response
from clock import clock, format_timestamp
from store import store
from errors import raise_error, ERR_VALIDATION
from services.dispatch import dispatch_order

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/advance", methods=["POST"])
def advance_clock():
    check_role_permission({"PlatformAdmin"})
    data = request.get_json(force=True, silent=True) or {}

    seconds = data.get("seconds")
    if seconds is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        raise_error(ERR_VALIDATION, "seconds must be a positive number")

    new_time = clock.advance(seconds)

    sweep_expired_offers()

    return success_response({"new_time": format_timestamp(new_time)})


def sweep_expired_offers():
    from clock import now
    current = now()
    from datetime import datetime, timezone

    expired = []
    for a in list(store.assignments.values()):
        if a["status"] != "OFFERED":
            continue
        offered_str = a.get("offered_at", "")
        try:
            offered_dt = datetime.strptime(offered_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
        if (current - offered_dt).total_seconds() >= 60:
            expired.append(a)

    for a in expired:
        a["status"] = "REJECTED"
        rider = store.riders.get(a["rider_id"])
        if rider:
            from services.rider_stats import recompute_acceptance_rate
            from services.computations import recompute_bonus_tier
            from models import touch
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)
            touch(rider)

        order = store.orders.get(a["order_id"])
        if order:
            dispatch_order(order)
