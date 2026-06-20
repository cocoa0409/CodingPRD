"""Outbreak clusters: list, get, close."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import touch, parse_pagination, sorted_by_creation, get_or_404
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_cluster

bp = Blueprint("clusters", __name__)

CLUSTER_READ_ROLES = {"JurisdictionAdmin", "CaseInvestigator", "ContactTracer", "EpiAnalyst"}


@bp.route("/surveillance/outbreak-clusters", methods=["GET"])
def list_clusters():
    _, role = get_user_context()
    require_role(role, CLUSTER_READ_ROLES)
    with db.lock:
        filters = ["program_id", "condition_code", "exposure_setting_location_id",
                   "status", "anchor_case_id"]
        items = []
        for c in db.clusters.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and c.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(c)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_cluster(c) for c in page], limit, offset, total)


@bp.route("/surveillance/outbreak-clusters/<cluster_id>", methods=["GET"])
def get_cluster(cluster_id):
    _, role = get_user_context()
    require_role(role, CLUSTER_READ_ROLES)
    with db.lock:
        c = get_or_404(db.clusters, cluster_id, "ERR_CLUSTER_NOT_FOUND")
        return success(ser_cluster(c), 200)


@bp.route("/surveillance/outbreak-clusters/<cluster_id>/close", methods=["POST"])
def close_cluster(cluster_id):
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    with db.lock:
        c = get_or_404(db.clusters, cluster_id, "ERR_CLUSTER_NOT_FOUND")
        if c["status"] != "ACTIVE":
            raise err("ERR_CLUSTER_NOT_CLOSEABLE", "Cluster not in ACTIVE for close")
        c["status"] = "CLOSED"
        touch(c)
        return success(ser_cluster(c), 200)
