"""MediaBatch routes (PRD §3.2)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_WINDOW_CLOSED,
)
from helpers import (
    new_entity,
    touch,
    now_iso,
    get_json_body,
    require_fields,
    check_string,
    check_datetime_string,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from services.derived import (
    recompute_batch_counters,
    recompute_project_storage,
    purge_batch_assets,
)
from clock import clock as logical_clock, _parse_iso

bp = Blueprint("batches", __name__)

BATCH_TERMINAL = ("READY", "PURGED")
LIST_ROLES = ("PostSupervisor", "MediaManager", "ConformEditor", "DailiesCoordinator")


def serialize(batch):
    return dict(batch)


def get_batch_or_404(project, batch_id):
    batch = db.batches.get(batch_id)
    if batch is None or batch["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    return batch


@bp.route("/post-production/projects/<project_id>/batches", methods=["POST"])
def create_batch(project_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("batch_label", "ingest_window_start", "ingest_window_end"))
    batch_label = check_string(body, "batch_label")
    ingest_window_start = check_datetime_string(body, "ingest_window_start")
    ingest_window_end = check_datetime_string(body, "ingest_window_end")
    if not (_parse_iso(ingest_window_end) > _parse_iso(ingest_window_start)):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'ingest_window_end' must be strictly greater than "
            "'ingest_window_start'",
            400,
        )
    # batch_label unique per project
    for existing in db.batches.values():
        if (
            existing["project_id"] == project_id
            and existing["batch_label"] == batch_label
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                f"batch_label '{batch_label}' already exists in this project",
                400,
            )
    batch = new_entity(
        {
            "project_id": project["id"],
            "batch_label": batch_label,
            "ingest_window_start": ingest_window_start,
            "ingest_window_end": ingest_window_end,
            "status": "DECLARED",
            "asset_count": 0,
            "failed_asset_count": 0,
            "proxy_progress_pct": 0,
        }
    )
    db.batches[batch["id"]] = batch
    return success_object(serialize(batch), 201)


@bp.route("/post-production/projects/<project_id>/batches", methods=["GET"])
def list_batches(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [b for b in db.batches.values() if b["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in window], limit, offset, total)


@bp.route("/post-production/projects/<project_id>/batches/<batch_id>", methods=["GET"])
def get_batch(project_id, batch_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    batch = get_batch_or_404(project, batch_id)
    return success_object(serialize(batch))


@bp.route(
    "/post-production/projects/<project_id>/batches/<batch_id>/start-ingest",
    methods=["POST"],
)
def start_ingest(project_id, batch_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    batch = get_batch_or_404(project, batch_id)
    # Project must be ACTIVE — an attempt on a non-ACTIVE project fails as an
    # invalid state transition (PRD §3.2).
    if project["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Project is in state {project['status']}, not ACTIVE",
            409,
        )
    guard_transition(batch, "DECLARED", BATCH_TERMINAL, "media batch")
    now = logical_clock.now()
    start = _parse_iso(batch["ingest_window_start"])
    end = _parse_iso(batch["ingest_window_end"])
    if not (start <= now <= end):
        raise ApiError(
            ERR_WINDOW_CLOSED,
            "Logical clock is outside the declared ingest window",
            422,
        )
    batch["status"] = "INGESTING"
    touch(batch)
    return success_object(serialize(batch))


@bp.route(
    "/post-production/projects/<project_id>/batches/<batch_id>/finish-ingest",
    methods=["POST"],
)
def finish_ingest(project_id, batch_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    batch = get_batch_or_404(project, batch_id)
    guard_transition(batch, "INGESTING", BATCH_TERMINAL, "media batch")
    recompute_batch_counters(batch)
    if batch["asset_count"] < 1 or batch["failed_asset_count"] != 0:
        raise ApiError(
            ERR_INVALID_STATE,
            "Batch must hold at least one asset and have failed_asset_count 0 "
            "to finish ingest",
            409,
        )
    batch["status"] = "PROXYING"
    touch(batch)
    # Every MediaAsset in batch: proxy_status PENDING -> RUNNING.
    for asset in db.assets.values():
        if asset.get("batch_id") == batch["id"] and asset["proxy_status"] == "PENDING":
            asset["proxy_status"] = "RUNNING"
            touch(asset)
    return success_object(serialize(batch))


@bp.route(
    "/post-production/projects/<project_id>/batches/<batch_id>/purge",
    methods=["POST"],
)
def purge_batch(project_id, batch_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    batch = get_batch_or_404(project, batch_id)
    # FAILED -> PURGED unconditional; READY -> PURGED guarded.
    if batch["status"] == "PURGED":
        raise ApiError(
            "ERR_ALREADY_TERMINAL",
            "Attempted transition on a media batch already in terminal state PURGED",
            409,
        )
    if batch["status"] not in ("FAILED", "READY"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"Media batch is in state {batch['status']}, not in FAILED or READY",
            409,
        )
    if batch["status"] == "READY":
        # No PUBLISHED DailiesPackage references this batch.
        for pkg in db.dailies_packages.values():
            if pkg.get("batch_id") == batch["id"] and pkg["status"] == "PUBLISHED":
                raise ApiError(
                    ERR_INVALID_STATE,
                    "A PUBLISHED DailiesPackage references this batch; purge refused",
                    409,
                )
        # No OPEN ChangeList entry references an asset in this batch.
        batch_asset_ids = {
            a["id"] for a in db.assets.values() if a.get("batch_id") == batch["id"]
        }
        for cl in db.change_lists.values():
            if cl["project_id"] != project_id or cl["status"] != "OPEN":
                continue
            for entry in cl.get("entries", []):
                if entry.get("asset_id") in batch_asset_ids:
                    raise ApiError(
                        ERR_INVALID_STATE,
                        "An OPEN ChangeList entry references an asset in this "
                        "batch; purge refused",
                        409,
                    )
    batch["status"] = "PURGED"
    touch(batch)
    purge_batch_assets(batch)
    recompute_project_storage(project)
    return success_object(serialize(batch))


# ---------------------------------------------------------------------------
# Flat alias + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/batches/<batch_id>", methods=["GET"])
def get_batch_flat(batch_id):
    require_roles(LIST_ROLES)
    batch = db.batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    return success_object(serialize(batch))


@bp.route("/post-production/batches/<batch_id>/assets", methods=["GET"])
def list_batch_assets(batch_id):
    require_roles(LIST_ROLES + ("QCOperator",))
    batch = db.batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    from routes.assets import serialize as serialize_asset

    limit, offset = get_pagination()
    items = [a for a in db.assets.values() if a.get("batch_id") == batch_id]
    status = get_filter("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    proxy_status = get_filter("proxy_status")
    if proxy_status is not None:
        items = [a for a in items if a["proxy_status"] == proxy_status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_asset(a) for a in window], limit, offset, total)


@bp.route("/post-production/batches/<batch_id>/dailies", methods=["GET"])
def list_batch_dailies(batch_id):
    require_roles(("PostSupervisor", "DailiesCoordinator", "ReviewerLead"))
    batch = db.batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    from routes.dailies import serialize as serialize_package

    limit, offset = get_pagination()
    items = [p for p in db.dailies_packages.values() if p.get("batch_id") == batch_id]
    status = get_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_package(p) for p in window], limit, offset, total)
