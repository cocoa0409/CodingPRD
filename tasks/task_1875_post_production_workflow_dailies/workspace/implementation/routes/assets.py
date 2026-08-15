"""MediaAsset routes (PRD §3.2)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_ASSET,
    ERR_STORAGE_QUOTA_EXCEEDED,
    ERR_INVALID_REQUEST,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_int,
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
    recompute_conform_ready,
)

bp = Blueprint("assets", __name__)

ASSET_TERMINAL = ("LOCKED", "PURGED")
LIST_ROLES = (
    "PostSupervisor",
    "MediaManager",
    "ConformEditor",
    "DailiesCoordinator",
    "QCOperator",
)

_GIB = 1024 ** 3


def serialize(asset):
    return dict(asset)


def get_asset_or_404(project, asset_id):
    asset = db.assets.get(asset_id)
    if asset is None or asset["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"MediaAsset {asset_id} does not exist", 404)
    return asset


@bp.route("/post-production/projects/<project_id>/assets", methods=["POST"])
def create_asset(project_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(
        body, ("batch_id", "reel_name", "clip_name", "source_bytes", "duration_frames")
    )
    batch_id = body["batch_id"]
    if not isinstance(batch_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'batch_id' must be a string", 400)
    # FK resolution (priority 3)
    batch = db.batches.get(batch_id)
    if batch is None or batch["project_id"] != project_id:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    reel_name = check_string(body, "reel_name")
    clip_name = check_string(body, "clip_name")
    source_bytes = check_int(body, "source_bytes", min_v=1)
    duration_frames = check_int(body, "duration_frames", min_v=1)

    # Asset uniqueness (priority 11): composite (project, reel, clip) unique
    # among non-PURGED assets.
    for existing in db.assets.values():
        if (
            existing["project_id"] == project_id
            and existing["status"] != "PURGED"
            and existing["reel_name"] == reel_name
            and existing["clip_name"] == clip_name
        ):
            raise ApiError(
                ERR_DUPLICATE_ASSET,
                "Composite (project_id, reel_name, clip_name) already present "
                "among non-PURGED MediaAssets",
                409,
            )

    # Storage quota (priority 14): current usage + incoming bytes must remain
    # at or below the quota. Storage accounting is kept in bytes (PRD §2.8);
    # the comparison is byte-exact and must NOT round the GiB sum first —
    # otherwise a full quota (e.g. exactly 1 GiB used of a 1 GiB quota) would
    # absorb sub-rounding-threshold additions (1 GiB + 1 byte rounds to 1.000)
    # and wrongly accept a registration that pushes usage past the quota.
    used_bytes = 0
    for a in db.assets.values():
        if a["project_id"] != project_id:
            continue
        if a["status"] == "PURGED":
            continue
        used_bytes += a["source_bytes"] + a["proxy_bytes"]
    if used_bytes + source_bytes > project["storage_quota_gb"] * _GIB:
        raise ApiError(
            ERR_STORAGE_QUOTA_EXCEEDED,
            "Project storage_used_gb + new asset bytes would exceed "
            "storage_quota_gb",
            422,
        )

    asset = new_entity(
        {
            "project_id": project_id,
            "batch_id": batch_id,
            "reel_name": reel_name,
            "clip_name": clip_name,
            "source_bytes": source_bytes,
            "proxy_bytes": 0,
            "duration_frames": duration_frames,
            "proxy_status": "PENDING",
            "status": "INGESTED",
            "qc_fail_count": 0,
            "retained_until": None,
        }
    )
    db.assets[asset["id"]] = asset
    recompute_batch_counters(batch)
    recompute_project_storage(project)
    recompute_conform_ready(project)
    return success_object(serialize(asset), 201)


@bp.route("/post-production/projects/<project_id>/assets", methods=["GET"])
def list_assets(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [a for a in db.assets.values() if a["project_id"] == project_id]
    batch_id = get_filter("batch_id")
    if batch_id is not None:
        items = [a for a in items if a.get("batch_id") == batch_id]
    status = get_filter("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    proxy_status = get_filter("proxy_status")
    if proxy_status is not None:
        items = [a for a in items if a["proxy_status"] == proxy_status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(a) for a in window], limit, offset, total)


@bp.route("/post-production/projects/<project_id>/assets/<asset_id>", methods=["GET"])
def get_asset(project_id, asset_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    asset = get_asset_or_404(project, asset_id)
    return success_object(serialize(asset))


@bp.route(
    "/post-production/projects/<project_id>/assets/<asset_id>/proxy-complete",
    methods=["POST"],
)
def proxy_complete(project_id, asset_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    asset = get_asset_or_404(project, asset_id)
    body = get_json_body()
    require_fields(body, ("proxy_bytes",))
    proxy_bytes = check_int(body, "proxy_bytes", min_v=0)
    asset["proxy_bytes"] = proxy_bytes
    asset["proxy_status"] = "DONE"
    touch(asset)
    batch = db.batches.get(asset["batch_id"])
    if batch is not None:
        recompute_batch_counters(batch)
        # If last outstanding asset in the batch reaches DONE, the batch
        # automatically transitions PROXYING -> READY.
        if batch["status"] == "PROXYING":
            batch_assets = [
                a for a in db.assets.values() if a.get("batch_id") == batch["id"]
            ]
            if batch_assets and all(
                a["proxy_status"] == "DONE" for a in batch_assets
            ):
                batch["status"] = "READY"
                touch(batch)
    recompute_project_storage(project)
    return success_object(serialize(asset))


@bp.route(
    "/post-production/projects/<project_id>/assets/<asset_id>/verify",
    methods=["POST"],
)
def verify_asset(project_id, asset_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    asset = get_asset_or_404(project, asset_id)
    guard_transition(asset, "INGESTED", ASSET_TERMINAL, "media asset")
    if asset["proxy_status"] != "DONE":
        raise ApiError(
            ERR_INVALID_STATE,
            "proxy_status must be DONE before verification",
            409,
        )
    asset["status"] = "VERIFIED"
    touch(asset)
    return success_object(serialize(asset))


@bp.route(
    "/post-production/projects/<project_id>/assets/<asset_id>/conform",
    methods=["POST"],
)
def conform_asset(project_id, asset_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    asset = get_asset_or_404(project, asset_id)
    guard_transition(asset, "VERIFIED", ASSET_TERMINAL, "media asset")
    if project["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Project is in state {project['status']}, not ACTIVE",
            409,
        )
    # Asset must be referenced by at least one CONFORM turnover in
    # {STAGED, ISSUED}.
    referenced = False
    for to in db.turnovers.values():
        if to["project_id"] != project_id:
            continue
        if to["turnover_kind"] != "CONFORM":
            continue
        if to["status"] not in ("STAGED", "ISSUED"):
            continue
        referenced = True
        break
    if not referenced:
        raise ApiError(
            ERR_INVALID_STATE,
            "Asset is not referenced by at least one CONFORM TurnoverPackage "
            "in STAGED or ISSUED",
            409,
        )
    asset["status"] = "CONFORMED"
    touch(asset)
    recompute_conform_ready(project)
    return success_object(serialize(asset))


@bp.route(
    "/post-production/projects/<project_id>/assets/<asset_id>/lock",
    methods=["POST"],
)
def lock_asset(project_id, asset_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    asset = get_asset_or_404(project, asset_id)
    guard_transition(asset, "CONFORMED", ASSET_TERMINAL, "media asset")
    # All ChangeLists referencing this asset must be in
    # {APPLIED, SUPERSEDED, REJECTED}.
    for cl in db.change_lists.values():
        if cl["project_id"] != project_id:
            continue
        if cl["status"] in ("APPLIED", "SUPERSEDED", "REJECTED"):
            continue
        for entry in cl.get("entries", []):
            if entry.get("asset_id") == asset_id:
                raise ApiError(
                    ERR_INVALID_STATE,
                    "A ChangeList referencing this asset is still OPEN",
                    409,
                )
    asset["status"] = "LOCKED"
    touch(asset)
    recompute_conform_ready(project)
    return success_object(serialize(asset))


# ---------------------------------------------------------------------------
# Flat alias + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/assets/<asset_id>", methods=["GET"])
def get_asset_flat(asset_id):
    require_roles(LIST_ROLES)
    asset = db.assets.get(asset_id)
    if asset is None:
        raise ApiError(ERR_NOT_FOUND, f"MediaAsset {asset_id} does not exist", 404)
    return success_object(serialize(asset))


@bp.route("/post-production/assets/<asset_id>/qc-reports", methods=["GET"])
def list_asset_qc_reports(asset_id):
    require_roles(("PostSupervisor", "ConformEditor", "QCOperator"))
    asset = db.assets.get(asset_id)
    if asset is None:
        raise ApiError(ERR_NOT_FOUND, f"MediaAsset {asset_id} does not exist", 404)
    from routes.deliverables import serialize_qc_report

    limit, offset = get_pagination()
    items = [r for r in db.qc_reports.values() if r.get("asset_id") == asset_id]
    verdict = get_filter("verdict")
    if verdict is not None:
        items = [r for r in items if r["verdict"] == verdict]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_qc_report(r) for r in window], limit, offset, total)
