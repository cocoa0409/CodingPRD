"""Test-only endpoints: clock advance + surge sweep."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_array, success_object, empty_success
from ..errors import err_invalid_input
from ..serializers import serialize_heatmap_snapshot
from ..services.quests import transition_quests_for_clock
from ..services.surge import recompute_surge
from ..store import reset_store, store
from ..util import new_uuid, parse_iso8601
from ._helpers import get_json, require_string

bp = Blueprint("clock_and_sweep", __name__)


@bp.route("/__test__/reset", methods=["POST"])
def test_reset():
    """Test-only: wipe in-memory store between tests."""
    reset_store()
    return jsonify(empty_success()), 200


@bp.route("/_clock/advance", methods=["POST"])
@require_roles(["PlatformAdmin"])
def advance_clock():
    body = get_json()
    target_s = require_string(body, "target_timestamp")
    try:
        target = parse_iso8601(target_s)
    except ValueError:
        raise err_invalid_input("target_timestamp must be ISO 8601")
    s = store()
    s.set_now(target)

    # Time-gated transitions: quest bonus SCHEDULED->ACTIVE->CLOSED.
    transition_quests_for_clock(target)

    return jsonify(empty_success()), 200


@bp.route("/_sweep/recompute_surge", methods=["POST"])
@require_roles(["PlatformAdmin"])
def sweep_recompute_surge():
    s = store()
    now = s.now()
    written = []
    for g in s.list_collection("grids"):
        recompute_surge(g, bump_version=True)
        snap_id = new_uuid()
        snap = {
            "id": snap_id,
            "grid_code": g["code"],
            "multiplier": g["current_multiplier"],
            "active_driver_count": g["active_driver_count"],
            "open_demand_count": g["open_demand_count"],
            "snapshot_at": now,
            "created_at": now,
        }
        s.insert("heatmap_snapshots", snap)
        written.append(snap)

    total = len(written)
    return jsonify(success_array(
        [serialize_heatmap_snapshot(x) for x in written],
        limit=total if total > 0 else 10,
        offset=0,
        total_count=total,
    )), 200
