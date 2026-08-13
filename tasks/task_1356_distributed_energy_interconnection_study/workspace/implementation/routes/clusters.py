"""ClusterGroup endpoints (scaffold section 1.5)."""
from flask import Blueprint

from clock import parse_iso
from db import DB, new_id, next_seq, pub, sort_key, stamp_new
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok, ok_list
from services import members_of, study_of_cluster
from util import body, pagination_args, req_dt_str, req_num, req_str

bp = Blueprint("clusters", __name__)


@bp.route("/interconnection/cluster-groups", methods=["POST"])
def create_cluster_group():
    auth(["QueueAdministrator"])
    data = body()
    name = req_str(data, "name")
    region = req_str(data, "region")
    window_open_raw = req_dt_str(data, "application_window_open")
    window_close_raw = req_dt_str(data, "application_window_close")
    capacity_mw = req_num(data, "capacity_mw")

    window_open = parse_iso(window_open_raw)
    window_close = parse_iso(window_close_raw)
    # Half-open window [open, close): close must be strictly later than open.
    if window_close <= window_open:
        raise ApiError(
            "ERR_INVALID_WINDOW", 400,
            "application_window_close must be strictly after application_window_open",
        )
    # Within a region, the windows of non-CLOSED clusters must not overlap;
    # half-open semantics make adjacency (close == open) permitted.
    for other in DB["cluster_groups"].values():
        if other["region"] != region or other["status"] == "CLOSED":
            continue
        other_open = parse_iso(other["application_window_open"])
        other_close = parse_iso(other["application_window_close"])
        if window_open < other_close and other_open < window_close:
            raise ApiError(
                "ERR_CLUSTER_WINDOW_OVERLAP", 409,
                "Application window overlaps another cluster's window in this region",
            )
    if not (capacity_mw > 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity_mw must be greater than 0")

    cluster = {
        "id": new_id(),
        "_seq": next_seq(),
        "name": name,
        "region": region,
        "application_window_open": window_open_raw,
        "application_window_close": window_close_raw,
        "capacity_mw": capacity_mw,
        "committed_mw": 0,
        "status": "FORMING",
    }
    stamp_new(cluster)
    DB["cluster_groups"][cluster["id"]] = cluster
    return ok(pub(cluster), 201)


@bp.route("/interconnection/cluster-groups/<cluster_id>", methods=["GET"])
def get_cluster_group(cluster_id):
    auth(READ_ROLES)
    cluster = DB["cluster_groups"].get(cluster_id)
    if cluster is None:
        raise ApiError("ERR_CLUSTER_GROUP_NOT_FOUND", 404, "ClusterGroup id does not exist")
    return ok(pub(cluster))


@bp.route("/interconnection/cluster-groups/<cluster_id>/projects", methods=["GET"])
def list_cluster_projects(cluster_id):
    auth(READ_ROLES)
    cluster = DB["cluster_groups"].get(cluster_id)
    if cluster is None:
        raise ApiError("ERR_CLUSTER_GROUP_NOT_FOUND", 404, "ClusterGroup id does not exist")
    limit, offset = pagination_args()
    items = members_of(cluster_id)
    page = items[offset:offset + limit]
    return ok_list([pub(p) for p in page], len(items), limit, offset)


@bp.route("/interconnection/cluster-groups/<cluster_id>/studies", methods=["GET"])
def list_cluster_studies(cluster_id):
    auth(READ_ROLES)
    cluster = DB["cluster_groups"].get(cluster_id)
    if cluster is None:
        raise ApiError("ERR_CLUSTER_GROUP_NOT_FOUND", 404, "ClusterGroup id does not exist")
    limit, offset = pagination_args()
    study = study_of_cluster(cluster_id)
    items = [study] if study is not None else []
    page = items[offset:offset + limit]
    return ok_list([pub(s) for s in page], len(items), limit, offset)
