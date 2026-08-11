"""Logical clock routes."""
from flask import Blueprint, request

from db import store, parse_iso, format_iso
from errors import err_invalid_request
from middleware import require_role
from response import success_object
from services.lifecycle import fire_time_transitions
from services.posture import recompute_network_posture, recompute_station_posture
from services.serializers import network_view


bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        raise err_invalid_request("to_iso8601 is required")
    try:
        new_dt = parse_iso(to_iso8601)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    # Must be non-decreasing relative to current logical clock
    try:
        current_dt = parse_iso(store.logical_clock_utc)
    except Exception:
        current_dt = None
    if current_dt is not None and new_dt < current_dt:
        raise err_invalid_request("to_iso8601 must be non-decreasing")
    store.logical_clock_utc = format_iso(new_dt)
    # Apply to all networks and fire time-triggered transitions
    last_network = None
    for n in store.networks.values():
        n["current_utc"] = store.logical_clock_utc
        fire_time_transitions(n)
        recompute_network_posture(n)
        last_network = n
    # Recompute station postures for all stations
    for s in store.stations.values():
        recompute_station_posture(s)
    # PRD §2.8: clock is server-wide, not network-scoped. Returning the most
    # recently touched network when present; otherwise echo the new clock.
    if last_network is None:
        return success_object({"current_utc": store.logical_clock_utc})
    return success_object(network_view(last_network))
