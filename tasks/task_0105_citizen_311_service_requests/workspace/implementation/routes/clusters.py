"""DuplicateCluster endpoints (PRD §3.7)."""
from flask import Blueprint, request as flask_request

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response
from services import calc, notify

bp = Blueprint("clusters", __name__)


@bp.route("/duplicate-clusters", methods=["POST"])
def create_cluster():
    p = authenticate()
    authorize(p, {"Dispatcher"})
    data = validate.body()
    category_id = validate.require_str(data, "category_id")
    canonical_request_id = validate.require_str(data, "canonical_request_id")
    expected_canonical_version = validate.require_int(data, "expected_canonical_version")

    # Existence (priority 3), left-to-right.
    if category_id not in db.categories:
        raise errors.not_found("Category not found.")
    canonical = db.service_requests.get(canonical_request_id)
    if canonical is None:
        raise errors.not_found("Canonical request not found.")

    # priority 7: OCC on canonical ServiceRequest version.
    if expected_canonical_version != canonical["version"]:
        raise errors.stale_version("Canonical request version is stale.")

    rec = {
        "category_id": category_id,
        "canonical_request_id": canonical_request_id,
        "center_lat": canonical.get("lat"),
        "center_lng": canonical.get("lng"),
        "member_count": 0,
        "status": "OPEN",
    }
    db.stamp_common(rec)
    db.clusters[rec["id"]] = rec
    return response.object_response(serialize.view("cluster", rec), 201)


@bp.route("/duplicate-clusters/<cid>", methods=["GET"])
def get_cluster(cid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    rec = db.clusters.get(cid)
    if rec is None:
        raise errors.not_found("Cluster not found.")
    return response.object_response(serialize.view("cluster", rec))


@bp.route("/duplicate-clusters", methods=["GET"])
def list_clusters():
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    limit, offset = validate.pagination()
    args = flask_request.args
    f_category = args.get("category_id")
    f_canonical = args.get("canonical_request_id")
    f_status = args.get("status")

    def pred(r):
        if f_category is not None and r["category_id"] != f_category:
            return False
        if f_canonical is not None and r["canonical_request_id"] != f_canonical:
            return False
        if f_status is not None and r["status"] != f_status:
            return False
        return True

    rows = db.ordered(db.clusters, pred)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("cluster", page), limit, offset, total)


@bp.route("/duplicate-clusters/<cid>/members", methods=["POST"])
def attach_member(cid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    cluster = db.clusters.get(cid)
    if cluster is None:
        raise errors.not_found("Cluster not found.")
    data = validate.body()
    request_id = validate.require_str(data, "request_id")
    req = db.service_requests.get(request_id)
    if req is None:
        raise errors.not_found("Request not found.")

    # priority 6: state — request must be SUBMITTED; cluster must be OPEN.
    if req["status"] != "SUBMITTED" or cluster["status"] != "OPEN":
        raise errors.invalid_state("Request must be SUBMITTED and cluster OPEN.")

    # priority 10: category match.
    if req["category_id"] != cluster["category_id"]:
        raise errors.cluster_category_mismatch()

    # priority 11: within cluster radius (haversine, inclusive).
    if (req.get("lat") is None or req.get("lng") is None or
            cluster.get("center_lat") is None or cluster.get("center_lng") is None or
            not calc.within_cluster_radius(req["lat"], req["lng"],
                                           cluster["center_lat"], cluster["center_lng"])):
        raise errors.outside_cluster_radius()

    # Side effects.
    req["cluster_id"] = cluster["id"]
    from_status = req["status"]
    req["status"] = "DUPLICATE"
    notify.synthesize(req, from_status, "DUPLICATE")
    db.touch(req)
    calc.recompute_cluster_member_count(cluster)
    return response.object_response(serialize.view("service_request", req))


@bp.route("/duplicate-clusters/<cid>/close", methods=["POST"])
def close_cluster(cid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    cluster = db.clusters.get(cid)
    if cluster is None:
        raise errors.not_found("Cluster not found.")
    # priority 6: state.
    if cluster["status"] != "OPEN":
        raise errors.invalid_state("Cluster is not OPEN.")
    # priority 14: canonical request RESOLVED/CLOSED.
    canonical = db.service_requests.get(cluster["canonical_request_id"])
    if canonical is None or canonical["status"] not in ("RESOLVED", "CLOSED"):
        raise errors.canonical_not_resolved()

    # For each DUPLICATE member: synthesize DUPLICATE->CLOSED notification, leave folded.
    members = db.ordered(
        db.service_requests,
        lambda r: r.get("cluster_id") == cluster["id"] and r["status"] == "DUPLICATE",
    )
    for m in members:
        notify.synthesize(m, "DUPLICATE", "CLOSED")

    cluster["status"] = "MERGED_CLOSED"
    db.touch(cluster)
    return response.object_response(serialize.view("cluster", cluster))
