from flask import Blueprint, request
from auth import require_roles
from errors import APIError
from models import assignments, riders
from response_envelope import success_response
from routes.orders import create_dispatch_assignment
from calculations import recompute_rider_bonus
import clock
from models import touch

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def advance_clock():
    data = request.get_json(force=True, silent=True) or {}
    seconds = data.get("seconds")
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        raise APIError("ERR_VALIDATION", "seconds must be a non-negative number")

    clock.advance(seconds)

    sweep_expired_offers()

    return success_response({"current_time": clock.format_timestamp(clock.now())})


def sweep_expired_offers():
    from datetime import datetime, timezone
    now = clock.now()

    to_reject = []
    for a in list(assignments.values()):
        if a["status"] != "OFFERED":
            continue
        offered_at = datetime.fromisoformat(a["offered_at"].replace("Z", "+00:00"))
        elapsed = (now - offered_at).total_seconds()
        if elapsed >= 60:
            to_reject.append(a)

    for a in to_reject:
        a["status"] = "REJECTED"

        rider = riders.get(a["rider_id"])
        if rider:
            from routes.assignments import recompute_acceptance_rate
            recompute_acceptance_rate(rider["id"])
            recompute_rider_bonus(rider)
            touch(rider)

        excluded = set()
        for ea in assignments.values():
            if ea["order_id"] == a["order_id"] and ea["status"] in ("REJECTED", "CANCELLED"):
                excluded.add(ea["rider_id"])
        create_dispatch_assignment(a["order_id"], excluded)
