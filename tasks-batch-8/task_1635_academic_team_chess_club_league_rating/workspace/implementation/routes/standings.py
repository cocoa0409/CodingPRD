from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404
from services.serializers import snapshot_json

bp = Blueprint("standings", __name__)

READ = ALL_ROLES


@bp.route("/api/standings-snapshots", methods=["GET"])
@require_roles(*READ)
def list_snapshots():
    items = list(store.snapshots.values())
    sid = request.args.get("season_id")
    if sid is not None:
        items = [s for s in items if s["season_id"] == sid]
    cid = request.args.get("club_id")
    if cid is not None:
        items = [s for s in items if s["club_id"] == cid]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([snapshot_json(s) for s in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/standings-snapshots/<snapshotId>", methods=["GET"])
@require_roles(*READ)
def get_snapshot(snapshotId):
    s = get_or_404(store.snapshots, snapshotId, "standing snapshot")
    return success_object(snapshot_json(s), 200)
