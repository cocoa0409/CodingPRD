"""CapacityHuddle snapshot, ops run (expiry sweep), and simulated clock control."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common
from services.listing import paginate

bp = Blueprint("capacity", __name__)


def _get_huddle_or_404(huddle_id):
    h = store.capacity_huddles.get(huddle_id)
    if h is None:
        raise err(errors.ERR_NOT_FOUND, "Capacity huddle not found")
    return h


@bp.route("/capacity-huddles", methods=["POST"])
def create_huddle():
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "FlowAdmin"})

    total_staffed = 0
    total_occupied = 0
    red_units = 0
    for unit in store.units.values():
        common.recompute_unit(unit)
        total_staffed += unit["staffed_bed_count"]
        total_occupied += unit["occupied_bed_count"]
        if unit["effective_posture"] == "RED":
            red_units += 1

    if total_staffed == 0:
        house_pct = 0.00
    else:
        pct = Decimal(total_occupied) / Decimal(total_staffed) * Decimal(100)
        house_pct = float(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    boarding_count = sum(1 for e in store.encounters.values() if e["status"] == "BOARDING")
    queued_count = sum(1 for r in store.bed_requests.values() if r["status"] == "QUEUED")

    now = store.clock_now()
    huddle = {
        "huddle_at": iso(now),
        "total_staffed_beds": total_staffed,
        "total_occupied_beds": total_occupied,
        "house_occupancy_pct": house_pct,
        "boarding_encounter_count": boarding_count,
        "queued_request_count": queued_count,
        "red_unit_count": red_units,
    }
    common.stamp_new(huddle)
    store.capacity_huddles[huddle["id"]] = huddle
    return success(common.serialize_huddle(huddle), status=201)


@bp.route("/capacity-huddles/<huddle_id>", methods=["GET"])
def get_huddle(huddle_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator"})
    h = _get_huddle_or_404(huddle_id)
    return success(common.serialize_huddle(h))


@bp.route("/capacity-huddles", methods=["GET"])
def list_huddles():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator"})
    limit, offset = parse_pagination()
    page, total = paginate(list(store.capacity_huddles.values()), limit, offset)
    return list_success([common.serialize_huddle(h) for h in page], limit, offset, total)


@bp.route("/ops/run", methods=["POST"])
def ops_run():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator"})
    store.ops_run_index += 1
    expired = []
    for req in store.bed_requests.values():
        if req["status"] == "QUEUED":
            age = store.ops_run_index - req["queued_ops_index"]
            if age >= common.REQUEST_EXPIRY_RUNS:
                req["status"] = "EXPIRED"
                common.touch(req)
                expired.append(req["id"])
    return success({"ops_run_index": store.ops_run_index, "expired_request_ids": expired})


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = authenticate()
    authorize(role, {"FlowAdmin"})
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        s = to_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    store.set_clock(dt)
    return success({"current_utc": iso(dt)})
