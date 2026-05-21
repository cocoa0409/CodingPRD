"""Test-driving endpoints: clock advance + overdue sweep."""
from flask import Blueprint, request

from ..auth import require_roles
from ..clock import clock, iso_now, parse_iso
from ..errors import raise_api_error
from ..responses import success_object
from ..services.toll_engine import overdue_sweep
from ..store import store
from ..validators import require_json, require_str


system_bp = Blueprint("system", __name__)


@system_bp.route("/__test__/reset", methods=["POST"])
def reset_store():
    """Test-only: wipe all in-memory state and clock override.

    Returns the current logical-clock "now" so tests can anchor their
    own clock tracker. This endpoint is benchmark infrastructure and is
    not part of the PRD-defined surface.
    """
    with store.lock:
        store.accounts.clear()
        store.vehicles.clear()
        store.transponders.clear()
        store.toll_events.clear()
        store.reload_events.clear()
        store.violations.clear()
        store.fines.clear()
        store.interop_policies.clear()
        store.autoreload_minute_guard.clear()
    # Reset clock override so subsequent iso_now() returns wall-clock now.
    clock._override = None
    return success_object({"now": iso_now()})


@system_bp.route("/_clock/advance", methods=["POST"])
@require_roles("AgencyAdmin")
def advance_clock():
    payload = require_json(request.get_json(silent=True))
    iso = require_str(payload, "to_iso8601", min_len=1, max_len=64)
    try:
        instant = parse_iso(iso)
    except ValueError:
        raise_api_error("ERR_VALIDATION", "Invalid to_iso8601 value.")
    clock.set(instant)
    swept = overdue_sweep()
    return success_object({"clock": iso, "fines_swept": swept})


@system_bp.route("/_sweep/run", methods=["POST"])
@require_roles("AgencyAdmin")
def run_sweep():
    swept = overdue_sweep()
    return success_object({"fines_swept": swept})
