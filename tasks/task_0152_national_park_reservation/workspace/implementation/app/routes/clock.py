"""Clock / sweep / wallet routes."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..auth import ROLE_SYSTEM_OPERATOR, ROLE_VISITOR, current_user_id, require_auth
from ..clock import advance_to, now_utc
from ..envelope import empty_success, success_object
from ..errors import APIError
from ..services.sweep import run_sweep
from ..services.wallet import write_ledger
from ..serializers import serialize_ledger_entry
from ..store import get_store
from ..validators import get_json_body, require_int, require_string
from ._helpers import lookup_visitor, require_visitor_ownership

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth([ROLE_SYSTEM_OPERATOR])
def clock_advance():
    body = get_json_body()
    target = require_string(body, "target_iso", min_len=1)
    try:
        advance_to(target)
    except ValueError as e:
        raise APIError("ERR_VALIDATION", str(e), 422)
    return jsonify(empty_success()), 200


@bp.post("/__test__/reset")
def test_reset():
    """Test-only hook: wipe all in-memory state and reset the virtual
    clock to real wall-clock now. Used by the test conftest between
    tests so each scenario starts from a clean slate.
    """
    from .. import clock as clock_mod
    store = get_store()
    with store.lock:
        store.parks.clear()
        store.visitors.clear()
        store.passes.clear()
        store.campgrounds.clear()
        store.lottery_permits.clear()
        store.backcountry_zones.clear()
        store.timed_entry_reservations.clear()
        store.campground_reservations.clear()
        store.lottery_applications.clear()
        store.backcountry_permits.clear()
        store.waitlist_entries.clear()
        store.ledger_entries.clear()
        store.park_names.clear()
        store.park_codes.clear()
        store.visitor_emails.clear()
        store.pass_serials.clear()
        store.campground_names.clear()
        store.zone_names.clear()
        store.lottery_names.clear()
    # Reset the virtual clock to real wall-clock now
    with clock_mod._CLOCK_LOCK:
        clock_mod._virtual_now = None
    now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(tz=timezone.utc).microsecond // 1000:03d}Z"
    return jsonify(success_object({"now": now_iso})), 200


@bp.post("/_sweep/run")
@require_auth([ROLE_SYSTEM_OPERATOR])
def sweep_run():
    run_sweep()
    return jsonify(empty_success()), 200


@bp.post("/visitors/<visitor_id>/wallet/deposit")
@require_auth([ROLE_SYSTEM_OPERATOR, ROLE_VISITOR])
def wallet_deposit(visitor_id: str):
    require_visitor_ownership(visitor_id)
    lookup_visitor(visitor_id)
    body = get_json_body()
    amount = require_int(body, "amount_cents", min_val=1)
    entry = write_ledger(visitor_id, "DEPOSIT", amount, "None", None)
    return jsonify(success_object(serialize_ledger_entry(entry))), 201
