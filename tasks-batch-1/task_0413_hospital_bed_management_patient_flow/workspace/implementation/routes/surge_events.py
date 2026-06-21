"""SurgeEvent: declare + stand-down, recomputing unit posture each way."""

from flask import Blueprint, request

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common
from services.listing import paginate

bp = Blueprint("surge_events", __name__)

SURGE_LEVELS = {"YELLOW", "RED"}
SURGE_STATUSES = {"OPEN", "STOOD_DOWN"}


def _get_surge_or_404(surge_id):
    s = store.surge_events.get(surge_id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Surge event not found")
    return s


@bp.route("/surge-events", methods=["POST"])
def create_surge():
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "FlowAdmin"})
    body = get_json_body()

    unit_id = body.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise err(errors.ERR_INVALID_REQUEST, "unit_id is required")
    if unit_id not in store.units:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "unit_id does not resolve")

    level = body.get("level")
    if level not in SURGE_LEVELS:
        raise err(errors.ERR_INVALID_REQUEST, "level must be YELLOW or RED")

    reason = body.get("reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise err(errors.ERR_INVALID_REQUEST, "reason must be a string")

    now = store.clock_now()
    surge = {
        "unit_id": unit_id,
        "level": level,
        "reason": reason,
        "status": "OPEN",
        "opened_at": iso(now),
        "stood_down_at": None,
    }
    common.stamp_new(surge)
    store.surge_events[surge["id"]] = surge
    common.recompute_unit(store.units[unit_id])
    return success(common.serialize_surge(surge), status=201)


@bp.route("/surge-events/<surge_id>", methods=["GET"])
def get_surge(surge_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator"})
    s = _get_surge_or_404(surge_id)
    return success(common.serialize_surge(s))


@bp.route("/surge-events", methods=["GET"])
def list_surges():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator"})
    limit, offset = parse_pagination()
    unit_filter = request.args.get("unit_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in SURGE_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    surges = list(store.surge_events.values())
    if unit_filter is not None:
        surges = [s for s in surges if s["unit_id"] == unit_filter]
    if status_filter is not None:
        surges = [s for s in surges if s["status"] == status_filter]
    page, total = paginate(surges, limit, offset)
    return list_success([common.serialize_surge(s) for s in page], limit, offset, total)


@bp.route("/surge-events/<surge_id>/stand-down", methods=["POST"])
def stand_down(surge_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "FlowAdmin"})
    s = _get_surge_or_404(surge_id)
    if s["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Surge event is not OPEN")
    now = store.clock_now()
    s["status"] = "STOOD_DOWN"
    s["stood_down_at"] = iso(now)
    common.touch(s)
    unit = store.units.get(s["unit_id"])
    if unit is not None:
        common.recompute_unit(unit)
    return success(common.serialize_surge(s))
