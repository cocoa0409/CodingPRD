"""Driver endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import success_object
from ..errors import (
    err_forbidden,
    err_invalid_state,
    err_not_owner,
    err_reference_not_found,
)
from ..serializers import serialize_driver
from ..services.quests import find_overlapping_quest_for_driver, quest_completed_rides_count
from ..services.surge import recompute_surge
from ..store import store
from ..util import new_uuid
from ._helpers import (
    check_version,
    get_driver_or_404,
    get_grid_by_code,
    get_json,
    get_quest_or_404,
    require_string,
)

bp = Blueprint("drivers", __name__)


@bp.route("/drivers", methods=["POST"])
@require_roles(["PlatformAdmin"])
def create_driver():
    body = get_json()
    name = require_string(body, "name")
    s = store()
    now = s.now()
    did = new_uuid()
    driver = {
        "id": did,
        "name": name,
        "status": "OFFLINE",
        "current_grid_code": None,
        "quest_id": None,
        "quest_completed_rides": 0,
        "total_earnings_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("drivers", driver)
    return jsonify(success_object(serialize_driver(driver))), 201


@bp.route("/drivers/<driver_id>", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver"])
def get_driver(driver_id):
    d = get_driver_or_404(driver_id)
    user_id, role = current_user()
    if role == "Driver" and user_id != driver_id:
        raise err_not_owner()
    return jsonify(success_object(serialize_driver(d))), 200


@bp.route("/drivers/<driver_id>/quest", methods=["PATCH"])
@require_roles(["Driver", "PlatformAdmin"])
def patch_driver_quest(driver_id):
    d = get_driver_or_404(driver_id)
    user_id, role = current_user()
    if role == "Driver" and user_id != driver_id:
        raise err_not_owner()

    body = get_json()
    # quest_id may be supplied as null to unenroll, or a string id to enroll.
    if "quest_id" not in body:
        from ..errors import err_invalid_input
        raise err_invalid_input("quest_id is required (use null to unenroll)")

    new_quest_id = body["quest_id"]
    if new_quest_id is not None and not isinstance(new_quest_id, str):
        from ..errors import err_invalid_input
        raise err_invalid_input("quest_id must be a string or null")

    # FK existence check for body
    new_quest = None
    if new_quest_id is not None:
        new_quest = store().quest_bonuses.get(new_quest_id)
        if new_quest is None:
            raise err_reference_not_found("quest_id does not reference an existing QuestBonus")

    # OCC
    check_version(d, body)

    # Quest enrollment overlap check uses CLOSED-closed semantics; only relevant if enrolling AND
    # driver currently has a different quest assigned.
    if new_quest is not None and d.get("quest_id") is not None and d["quest_id"] != new_quest_id:
        cur_q = store().quest_bonuses.get(d["quest_id"])
        if cur_q is not None:
            # Check closed-closed overlap between current quest and the new one
            from ..services.quests import quest_intervals_overlap_closed
            from ..errors import err_quest_window_overlap
            if quest_intervals_overlap_closed(
                cur_q["window_start"], cur_q["window_end"],
                new_quest["window_start"], new_quest["window_end"],
            ):
                raise err_quest_window_overlap()

    # Apply enrollment
    d["quest_id"] = new_quest_id
    # Reset quest_completed_rides when changing quests; recompute against the new quest's window.
    if new_quest is not None:
        d["quest_completed_rides"] = quest_completed_rides_count(d["id"], new_quest)
    else:
        d["quest_completed_rides"] = 0

    s = store()
    d["updated_at"] = s.now()
    d["version"] += 1
    return jsonify(success_object(serialize_driver(d))), 200


@bp.route("/drivers/<driver_id>/go-online", methods=["POST"])
@require_roles(["Driver"])
def go_online(driver_id):
    d = get_driver_or_404(driver_id)
    user_id, role = current_user()
    if user_id != driver_id:
        raise err_not_owner()

    body = get_json()
    grid_code = require_string(body, "grid_code")
    grid = get_grid_by_code(grid_code)
    if grid is None:
        raise err_reference_not_found("grid_code does not reference an existing grid")

    if d["status"] != "OFFLINE":
        raise err_invalid_state()

    # Side effects
    d["current_grid_code"] = grid_code
    d["status"] = "AVAILABLE"
    grid["active_driver_count"] += 1
    s = store()
    d["updated_at"] = s.now()
    d["version"] += 1
    recompute_surge(grid, bump_version=True)
    return jsonify(success_object(serialize_driver(d))), 200


@bp.route("/drivers/<driver_id>/go-offline", methods=["POST"])
@require_roles(["Driver"])
def go_offline(driver_id):
    d = get_driver_or_404(driver_id)
    user_id, role = current_user()
    if user_id != driver_id:
        raise err_not_owner()

    if d["status"] != "AVAILABLE":
        raise err_invalid_state()

    cur_grid = get_grid_by_code(d["current_grid_code"]) if d["current_grid_code"] else None
    d["status"] = "OFFLINE"
    if cur_grid is not None:
        cur_grid["active_driver_count"] -= 1
    d["current_grid_code"] = None
    s = store()
    d["updated_at"] = s.now()
    d["version"] += 1
    if cur_grid is not None:
        recompute_surge(cur_grid, bump_version=True)
    return jsonify(success_object(serialize_driver(d))), 200
