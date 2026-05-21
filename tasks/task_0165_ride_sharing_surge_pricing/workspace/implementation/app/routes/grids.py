"""Grid endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import parse_pagination, paginate, success_array, success_object
from ..errors import APIError, err_invalid_input
from ..serializers import serialize_grid, serialize_heatmap_snapshot
from ..services.surge import recompute_surge
from ..store import store
from ..util import new_uuid
from ._helpers import (
    GRID_CODE_PATTERN,
    check_version,
    get_grid_or_404,
    get_json,
    optional_bool,
    optional_string,
    require_string,
)

bp = Blueprint("grids", __name__)


@bp.route("/grids", methods=["POST"])
@require_roles(["PlatformAdmin"])
def create_grid():
    body = get_json()
    code = require_string(body, "code")
    if not GRID_CODE_PATTERN.match(code):
        raise err_invalid_input("Invalid grid code format; must match ^G-[0-9]{3}$")
    s = store()
    if code in s.grid_code_index:
        raise err_invalid_input("Grid code already exists")
    name = require_string(body, "name")
    is_airport = body.get("is_airport", False)
    if not isinstance(is_airport, bool):
        raise err_invalid_input("is_airport must be a boolean")
    rush_hour_eligible = body.get("rush_hour_eligible", True)
    if not isinstance(rush_hour_eligible, bool):
        raise err_invalid_input("rush_hour_eligible must be a boolean")

    now = s.now()
    gid = new_uuid()
    grid = {
        "id": gid,
        "code": code,
        "name": name,
        "is_airport": is_airport,
        "rush_hour_eligible": rush_hour_eligible,
        "active_driver_count": 0,
        "open_demand_count": 0,
        "current_multiplier": Decimal("1.00"),
        "last_surge_recomputed_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    # Apply airport surcharge correctly from creation (even with 0/0 supply/demand).
    # surge formula: 0/0 -> raw=1.00, + airport surcharge if airport, then cap.
    s.insert("grids", grid)
    s.grid_code_index[code] = gid
    # Initial surge baseline; do NOT bump version (this is part of the create mutation).
    recompute_surge(grid, bump_version=False)
    grid["updated_at"] = now

    return jsonify(success_object(serialize_grid(grid))), 201


@bp.route("/grids", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver", "Rider", "DisputeOps"])
def list_grids():
    limit, offset = parse_pagination()
    items = store().list_collection("grids")
    items_sorted = sorted(items, key=lambda x: x["created_at"])
    total = len(items_sorted)
    page = paginate(items_sorted, limit, offset)
    return jsonify(
        success_array([serialize_grid(g) for g in page], limit=limit, offset=offset, total_count=total)
    ), 200


@bp.route("/grids/heatmap", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver", "Rider", "DisputeOps"])
def heatmap():
    """Return the latest HeatMapSnapshot per grid_code (descending snapshot_at)."""
    snaps = store().list_collection("heatmap_snapshots")
    latest_per_grid = {}
    for s in snaps:
        gc = s["grid_code"]
        if gc not in latest_per_grid or s["snapshot_at"] > latest_per_grid[gc]["snapshot_at"]:
            latest_per_grid[gc] = s
    # Sort descending by snapshot_at
    out = sorted(latest_per_grid.values(), key=lambda x: x["snapshot_at"], reverse=True)
    # Return as array — use the array envelope without pagination filters; treat as the full collection.
    total = len(out)
    return jsonify(
        success_array(
            [serialize_heatmap_snapshot(x) for x in out],
            limit=total if total > 0 else 10,
            offset=0,
            total_count=total,
        )
    ), 200


@bp.route("/grids/<grid_id>", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver", "Rider", "DisputeOps"])
def get_grid(grid_id):
    g = get_grid_or_404(grid_id)
    return jsonify(success_object(serialize_grid(g))), 200


@bp.route("/grids/<grid_id>", methods=["PATCH"])
@require_roles(["PlatformAdmin"])
def patch_grid(grid_id):
    g = get_grid_or_404(grid_id)
    body = get_json()
    check_version(g, body)

    new_name = optional_string(body, "name")
    new_rhe = optional_bool(body, "rush_hour_eligible")
    s = store()
    now = s.now()

    if new_name is not None:
        if new_name == "":
            raise err_invalid_input("name must be non-empty")
        g["name"] = new_name
    if new_rhe is not None:
        g["rush_hour_eligible"] = new_rhe

    # Single logical mutation -> bump version once via recompute_surge.
    recompute_surge(g, bump_version=True)
    return jsonify(success_object(serialize_grid(g))), 200
