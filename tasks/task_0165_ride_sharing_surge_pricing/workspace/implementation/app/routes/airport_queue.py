"""Airport queue endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import current_user, require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_driver_not_in_grid,
    err_invalid_state,
    err_not_airport_grid,
    err_not_owner,
    err_reference_not_found,
)
from ..serializers import serialize_airport_queue, serialize_driver
from ..services.queue import (
    append_to_queue,
    driver_in_any_queue,
    queue_rows_for_grid,
    remove_from_queue,
)
from ..services.surge import recompute_surge
from ..store import store
from ..util import new_uuid
from ._helpers import (
    get_grid_by_code,
    get_json,
    require_string,
)

bp = Blueprint("airport_queue", __name__)


@bp.route("/airport-queue/join", methods=["POST"])
@require_roles(["Driver"])
def join_queue():
    body = get_json()
    grid_code = require_string(body, "grid_code")

    user_id, _role = current_user()
    s = store()
    driver = s.drivers.get(user_id)
    if driver is None:
        # Driver path-id ownership: in this endpoint the acting driver IS the resource.
        raise err_not_owner()

    grid = get_grid_by_code(grid_code)
    if grid is None:
        raise err_reference_not_found("grid_code does not reference an existing grid")

    # State check first (per validations priority 7 BEFORE business_constraint 9/10).
    if driver["status"] != "AVAILABLE":
        raise err_invalid_state()

    # Business constraint 9: must be airport grid.
    if not grid["is_airport"]:
        raise err_not_airport_grid()

    # Business constraint 10: driver must be in this grid.
    if driver["current_grid_code"] != grid_code:
        raise err_driver_not_in_grid()

    # Already in any queue check (also part of preconditions)
    if driver_in_any_queue(driver["id"]) is not None:
        raise err_invalid_state("Driver is already in an airport queue")

    now = s.now()
    row_id = new_uuid()
    row = append_to_queue(grid_code, driver["id"], row_id, joined_at=now, created_at=now)

    driver["status"] = "IN_AIRPORT_QUEUE"
    driver["updated_at"] = now
    driver["version"] += 1

    # Queued drivers do NOT count toward supply.
    grid["active_driver_count"] -= 1
    recompute_surge(grid, bump_version=True)

    return jsonify(success_object(serialize_airport_queue(row))), 201


@bp.route("/airport-queue/leave", methods=["POST"])
@require_roles(["Driver"])
def leave_queue():
    user_id, _role = current_user()
    s = store()
    driver = s.drivers.get(user_id)
    if driver is None:
        raise err_not_owner()

    if driver["status"] != "IN_AIRPORT_QUEUE":
        raise err_invalid_state()

    row = driver_in_any_queue(driver["id"])
    if row is None:
        # Inconsistent state; treat as invalid.
        raise err_invalid_state()

    grid = get_grid_by_code(row["grid_code"])
    remove_from_queue(row["id"])

    driver["status"] = "AVAILABLE"
    now = s.now()
    driver["updated_at"] = now
    driver["version"] += 1

    if grid is not None:
        grid["active_driver_count"] += 1
        recompute_surge(grid, bump_version=True)

    return jsonify(success_object(serialize_driver(driver))), 200


@bp.route("/airport-queue", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver", "DisputeOps"])
def list_queue():
    limit, offset = parse_pagination()
    grid_code = request.args.get("grid_code")
    if not grid_code:
        from ..errors import err_invalid_input
        raise err_invalid_input("grid_code query parameter is required")
    rows = queue_rows_for_grid(grid_code)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return jsonify(success_array(
        [serialize_airport_queue(r) for r in page], limit=limit, offset=offset, total_count=total
    )), 200
