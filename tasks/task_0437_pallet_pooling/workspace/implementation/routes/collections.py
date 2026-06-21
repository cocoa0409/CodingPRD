"""CollectionRequest and RepairJob routes (PRD §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("collections", __name__)


# ---------------------------------------------------------------------------
# CollectionRequest (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/collection-requests", methods=["POST"])
def create_collection_request():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "location_id", db.locations)
    core.resolve_body_fk_list(body, "asset_ids", db.assets)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["location_id", "asset_ids"])
    location_id = core.require_str(body, "location_id")
    # asset_ids must be non-empty for collection requests (PRD §2.10).
    asset_ids = core.require_id_list(body, "asset_ids", allow_empty=False)

    # Each asset must sit at location_id and be AVAILABLE or DAMAGED (PRD §3.8).
    for aid in asset_ids:
        a = db.assets[aid]
        if a["current_location_id"] != location_id:
            raise err("ERR_ASSET_WRONG_LOCATION",
                      "Asset %s is not at the collection location" % aid)
        if a["condition"] not in ("AVAILABLE", "DAMAGED"):
            raise err("ERR_ASSET_NOT_AVAILABLE",
                      "Asset %s is not AVAILABLE or DAMAGED" % aid)

    req = core.stamp_new({
        "location_id": location_id,
        "asset_ids": list(asset_ids),
        "status": "REQUESTED",
    })
    db.collection_requests[req["id"]] = req
    return object_response(core.public(req), 201)


@bp.route("/collection-requests/<collection_request_id>", methods=["GET"])
def get_collection_request(collection_request_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    req = core.require(db.collection_requests, collection_request_id)
    return object_response(core.public(req), 200)


@bp.route("/collection-requests", methods=["GET"])
def list_collection_requests():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.collection_requests.values())
    for field in ("location_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/collection-requests/<collection_request_id>/collect", methods=["POST"])
def collect_collection_request(collection_request_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    req = core.require(db.collection_requests, collection_request_id)
    # REQUESTED -> COLLECTED (PRD §3.8) -> ERR_INVALID_STATE.
    if req["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Collection request is not REQUESTED")
    # Every asset's current_location_id == location_id (PRD §3.8).
    for aid in req["asset_ids"]:
        a = db.assets.get(aid)
        if a is None or a["current_location_id"] != req["location_id"]:
            raise err("ERR_ASSET_WRONG_LOCATION",
                      "Asset %s is not at the collection location" % aid)
    # Commit: each asset leaves the location (PRD §3.8).
    touched_locs = set()
    for aid in req["asset_ids"]:
        a = db.assets[aid]
        touched_locs.add(a["current_location_id"])
        if a["condition"] == "AVAILABLE":
            a["condition"] = "IN_TRANSIT"
            a["current_location_id"] = None
        else:  # DAMAGED: retains DAMAGED, location cleared
            a["current_location_id"] = None
        core.touch(a)
    req["status"] = "COLLECTED"
    core.touch(req)
    # physical_balance decremented (recompute) (PRD §3.8).
    for lid in touched_locs:
        loc = db.locations.get(lid)
        if loc is not None:
            core.recompute_location_derived(loc)
            core.touch(loc)
    return object_response(core.public(req), 200)


@bp.route("/collection-requests/<collection_request_id>/close", methods=["POST"])
def close_collection_request(collection_request_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    req = core.require(db.collection_requests, collection_request_id)
    # COLLECTED -> CLOSED (PRD §3.8) -> ERR_INVALID_STATE.
    if req["status"] != "COLLECTED":
        raise err("ERR_INVALID_STATE", "Only a COLLECTED request can be closed")
    req["status"] = "CLOSED"
    core.touch(req)
    return object_response(core.public(req), 200)


@bp.route("/collection-requests/<collection_request_id>/cancel", methods=["POST"])
def cancel_collection_request(collection_request_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    req = core.require(db.collection_requests, collection_request_id)
    # REQUESTED -> CANCELLED (PRD §3.8) -> ERR_INVALID_STATE.
    if req["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED request can be cancelled")
    req["status"] = "CANCELLED"
    core.touch(req)
    return object_response(core.public(req), 200)


# ---------------------------------------------------------------------------
# RepairJob (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/repair-jobs", methods=["POST"])
def create_repair_job():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "collection_request_id", db.collection_requests)
    core.resolve_body_fk_list(body, "asset_ids", db.assets)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["collection_request_id", "asset_ids", "repair_cost_cents"])
    collection_request_id = core.require_str(body, "collection_request_id")
    # asset_ids must be non-empty for repair jobs (PRD §2.10).
    asset_ids = core.require_id_list(body, "asset_ids", allow_empty=False)
    repair_cost = core.require_int(body, "repair_cost_cents", minimum=0)

    # Each asset must be DAMAGED at job creation (PRD §3.8) -> ERR_ASSET_NOT_DAMAGED.
    for aid in asset_ids:
        a = db.assets[aid]
        if a["condition"] != "DAMAGED":
            raise err("ERR_ASSET_NOT_DAMAGED", "Asset %s is not DAMAGED" % aid)

    job = core.stamp_new({
        "collection_request_id": collection_request_id,
        "asset_ids": list(asset_ids),
        "repair_cost_cents": repair_cost,
        "status": "OPEN",
    })
    db.repair_jobs[job["id"]] = job
    # Each asset DAMAGED -> IN_REPAIR (PRD §3.8).
    for aid in asset_ids:
        a = db.assets[aid]
        a["condition"] = "IN_REPAIR"
        core.touch(a)
    return object_response(core.public(job), 201)


@bp.route("/repair-jobs/<repair_job_id>", methods=["GET"])
def get_repair_job(repair_job_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    job = core.require(db.repair_jobs, repair_job_id)
    return object_response(core.public(job), 200)


@bp.route("/repair-jobs", methods=["GET"])
def list_repair_jobs():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.repair_jobs.values())
    for field in ("collection_request_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [j for j in items if j[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/repair-jobs/<repair_job_id>/complete", methods=["POST"])
def complete_repair_job(repair_job_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    job = core.require(db.repair_jobs, repair_job_id)
    # OPEN -> COMPLETED (PRD §3.8) -> ERR_INVALID_STATE.
    if job["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Repair job is not OPEN")
    # Assets IN_REPAIR -> AVAILABLE at source collection origin (depot) (PRD §3.8).
    col = db.collection_requests.get(job["collection_request_id"])
    depot_location_id = col["location_id"] if col is not None else None
    for aid in job["asset_ids"]:
        a = db.assets.get(aid)
        if a is not None and a["condition"] == "IN_REPAIR":
            a["condition"] = "AVAILABLE"
            a["current_location_id"] = depot_location_id
            core.touch(a)
    job["status"] = "COMPLETED"
    core.touch(job)
    # Depot physical_balance incremented (recompute) (PRD §3.8).
    if depot_location_id is not None:
        depot = db.locations.get(depot_location_id)
        if depot is not None:
            core.recompute_location_derived(depot)
            core.touch(depot)
    return object_response(core.public(job), 200)


@bp.route("/repair-jobs/<repair_job_id>/scrap", methods=["POST"])
def scrap_repair_job(repair_job_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    job = core.require(db.repair_jobs, repair_job_id)
    # OPEN -> SCRAPPED (PRD §3.8) -> ERR_INVALID_STATE.
    if job["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Repair job is not OPEN")
    # Assets IN_REPAIR -> LOST (permanent removal) (PRD §3.8).
    for aid in job["asset_ids"]:
        a = db.assets.get(aid)
        if a is not None and a["condition"] == "IN_REPAIR":
            a["condition"] = "LOST"
            a["current_location_id"] = None
            core.touch(a)
    job["status"] = "SCRAPPED"
    core.touch(job)
    return object_response(core.public(job), 200)
