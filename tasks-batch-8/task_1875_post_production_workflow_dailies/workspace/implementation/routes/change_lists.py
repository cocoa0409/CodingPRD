"""ChangeList routes (PRD §3.5)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_ASSET_NOT_CONFORMABLE,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from services.derived import (
    recompute_conform_ready,
    recompute_open_change_list_count,
    recompute_turnover_change_list_revision,
)

bp = Blueprint("change_lists", __name__)

CL_TERMINAL = ("APPLIED", "REJECTED")
OPERATIONS = ("ADD", "DELETE", "TRIM", "SLIP")
LIST_ROLES = ("PostSupervisor", "ConformEditor", "VendorRep")


def serialize(change_list):
    return dict(change_list)


def get_change_list_or_404(project, change_list_id):
    cl = db.change_lists.get(change_list_id)
    if cl is None or cl["project_id"] != project["id"]:
        raise ApiError(
            ERR_NOT_FOUND, f"ChangeList {change_list_id} does not exist", 404
        )
    return cl


def _validate_entries(body):
    entries = body["entries"]
    if not isinstance(entries, list):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'entries' must be an array", 400)
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError(
                ERR_INVALID_REQUEST, "Each entry must be an object", 400
            )
        for field in ("asset_id", "operation", "frames_delta"):
            if field not in entry or entry[field] is None:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    f"Each entry requires '{field}'",
                    400,
                )
        if not isinstance(entry["asset_id"], str):
            raise ApiError(
                ERR_INVALID_REQUEST, "Entry 'asset_id' must be a string", 400
            )
        if entry["operation"] not in OPERATIONS:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Entry 'operation' must be one of ADD, DELETE, TRIM, SLIP",
                400,
            )
        if not isinstance(entry["frames_delta"], int) or isinstance(
            entry["frames_delta"], bool
        ):
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Entry 'frames_delta' must be an integer",
                400,
            )
    return entries


def _net_frames_delta(entries):
    total = 0
    for entry in entries:
        if entry["operation"] in ("ADD", "SLIP"):
            total += entry["frames_delta"]
        else:  # TRIM, DELETE contribute negative values
            total -= entry["frames_delta"]
    return total


@bp.route("/post-production/projects/<project_id>/change-lists", methods=["POST"])
def create_change_list(project_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("turnover_id", "entries"))
    turnover_id = body["turnover_id"]
    if not isinstance(turnover_id, str):
        raise ApiError(
            ERR_INVALID_REQUEST, "Field 'turnover_id' must be a string", 400
        )
    # FK resolution (priority 3)
    turnover = db.turnovers.get(turnover_id)
    if turnover is None or turnover["project_id"] != project_id:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    entries = _validate_entries(body)
    # Each entry.asset_id must resolve (FK resolution).
    for entry in entries:
        asset = db.assets.get(entry["asset_id"])
        if asset is None or asset["project_id"] != project_id:
            raise ApiError(
                ERR_NOT_FOUND,
                f"MediaAsset {entry['asset_id']} does not exist",
                404,
            )
    # revision := next per-turnover monotone integer, starts at 1.
    highest = 0
    for cl in db.change_lists.values():
        if cl.get("turnover_id") == turnover_id:
            highest = max(highest, cl["revision"])
    change_list = new_entity(
        {
            "project_id": project_id,
            "turnover_id": turnover_id,
            "revision": highest + 1,
            "entries": [dict(e) for e in entries],
            "net_frames_delta": _net_frames_delta(entries),
            "status": "OPEN",
        }
    )
    db.change_lists[change_list["id"]] = change_list
    recompute_turnover_change_list_revision(turnover)
    recompute_open_change_list_count(project)
    return success_object(serialize(change_list), 201)


@bp.route("/post-production/projects/<project_id>/change-lists", methods=["GET"])
def list_change_lists(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [c for c in db.change_lists.values() if c["project_id"] == project_id]
    turnover_id = get_filter("turnover_id")
    if turnover_id is not None:
        items = [c for c in items if c.get("turnover_id") == turnover_id]
    status = get_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(c) for c in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/change-lists/<change_list_id>/apply",
    methods=["POST"],
)
def apply_change_list(project_id, change_list_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    change_list = get_change_list_or_404(project, change_list_id)
    body = get_json_body()
    require_fields(body, ("expected_turnover_version",))
    expected = body["expected_turnover_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'expected_turnover_version' must be an integer",
            400,
        )
    turnover = db.turnovers.get(change_list["turnover_id"])
    if turnover is None:
        raise ApiError(
            ERR_NOT_FOUND,
            f"TurnoverPackage {change_list['turnover_id']} does not exist",
            404,
        )
    # Stale-version guard (priority 5) — OCC on the parent turnover.
    if expected != turnover["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_turnover_version does not match the turnover's current "
            "version",
            412,
        )
    # From-state (priority 6)
    guard_transition(change_list, "OPEN", CL_TERMINAL, "change list")
    if turnover["status"] not in ("ISSUED", "ACKED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Parent TurnoverPackage must be in ISSUED or ACKED to apply a "
            "change list",
            409,
        )
    # Conformability (priority 17): every entry.asset_id must resolve to a
    # MediaAsset in {VERIFIED, CONFORMED, LOCKED}.
    for entry in change_list["entries"]:
        asset = db.assets.get(entry["asset_id"])
        if asset is None:
            raise ApiError(
                ERR_NOT_FOUND,
                f"MediaAsset {entry['asset_id']} does not exist",
                404,
            )
        if asset["status"] not in ("VERIFIED", "CONFORMED", "LOCKED"):
            raise ApiError(
                ERR_ASSET_NOT_CONFORMABLE,
                "ChangeList entry references an asset not in VERIFIED, "
                "CONFORMED, or LOCKED",
                422,
            )
    # Apply side effects.
    change_list["status"] = "APPLIED"
    touch(change_list)
    # For each TRIM/DELETE entry: MediaAsset.duration_frames adjusted by
    # frames_delta (DELETE sets the duration contribution to zero within this
    # turnover's scope).
    for entry in change_list["entries"]:
        if entry["operation"] in ("TRIM", "DELETE"):
            asset = db.assets[entry["asset_id"]]
            if entry["operation"] == "DELETE":
                new_duration = 0
            else:  # TRIM
                new_duration = asset["duration_frames"] - entry["frames_delta"]
                if new_duration < 0:
                    new_duration = 0
            if asset["duration_frames"] != new_duration:
                asset["duration_frames"] = new_duration
                touch(asset)
    # Every other OPEN change list on the same turnover -> SUPERSEDED.
    for other in db.change_lists.values():
        if (
            other.get("turnover_id") == turnover["id"]
            and other["id"] != change_list["id"]
            and other["status"] == "OPEN"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    # TurnoverPackage.version increments by 1.
    touch(turnover)
    recompute_conform_ready(project)
    recompute_open_change_list_count(project)
    return success_object(serialize(change_list))


@bp.route(
    "/post-production/projects/<project_id>/change-lists/<change_list_id>/reject",
    methods=["POST"],
)
def reject_change_list(project_id, change_list_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    change_list = get_change_list_or_404(project, change_list_id)
    guard_transition(change_list, "OPEN", CL_TERMINAL, "change list")
    change_list["status"] = "REJECTED"
    touch(change_list)
    recompute_open_change_list_count(project)
    recompute_conform_ready(project)
    return success_object(serialize(change_list))


# ---------------------------------------------------------------------------
# Flat alias
# ---------------------------------------------------------------------------


@bp.route("/post-production/change-lists/<change_list_id>", methods=["GET"])
def get_change_list_flat(change_list_id):
    require_roles(LIST_ROLES)
    cl = db.change_lists.get(change_list_id)
    if cl is None:
        raise ApiError(
            ERR_NOT_FOUND, f"ChangeList {change_list_id} does not exist", 404
        )
    return success_object(serialize(cl))
