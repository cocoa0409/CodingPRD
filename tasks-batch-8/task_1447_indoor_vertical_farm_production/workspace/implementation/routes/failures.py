"""Routes: failure reports and replant requests."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import get_body, get_body_optional, pagination_params, req_enum, dec, q2
from services.core import (
    stamp_new, touch, logical_now,
    get_failure, get_replant, get_batch,
    ser_failure, ser_replant, ser_batch,
    CAUSE_CATEGORIES, active_allocations_of_batch, intervals_overlap_half_open,
)
from services.calculations import compute_replant_priority, select_towers_for_replant

bp = Blueprint("failures", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/failure-reports")
def list_failures():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.failure_reports.values())
    bid = _q("batch_id")
    st = _q("report_status")
    if bid is not None:
        items = [f for f in items if f["batch_id"] == bid]
    if st is not None:
        items = [f for f in items if f["report_status"] == st]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    return list_response(items, ser_failure, limit, offset)


@bp.get("/failure-reports/<fid>")
def get_failure_route(fid):
    require_roles(*ALL_ROLES)
    return success(ser_failure(get_failure(fid)))


@bp.post("/failure-reports/<fid>/triage")
def triage_failure(fid):
    user_id, _ = require_roles("Grower")
    body = get_body({"cause_category", "lost_lb_estimate"}, {"cause_category", "lost_lb_estimate"})
    failure = get_failure(fid)
    if failure["report_status"] != "REPORTED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Failure not REPORTED")
    cause = req_enum(body["cause_category"], "cause_category", CAUSE_CATEGORIES)
    lost = dec(body["lost_lb_estimate"], "lost_lb_estimate")
    if lost < 0:
        raise_error("ERR_INVALID_REQUEST", "lost_lb_estimate must be non-negative")
    failure["cause_category"] = cause
    failure["lost_lb_estimate"] = q2(lost)
    failure["triaged_by_user_id"] = user_id
    failure["report_status"] = "TRIAGED"
    touch(failure)
    return success(ser_failure(failure))


@bp.post("/failure-reports/<fid>/request-replant")
def request_replant(fid):
    require_roles("Grower")
    get_body_optional(set())
    failure = get_failure(fid)
    if failure["report_status"] not in ("TRIAGED", "REPLANT_REQUESTED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Failure not TRIAGED/REPLANT_REQUESTED")
    for r in store.replant_requests.values():
        if r["failure_id"] == fid and r["replant_status"] == "QUEUED":
            raise_error("ERR_REPLANT_ALREADY_QUEUED", "Replant already queued")
    batch = get_batch(failure["batch_id"])
    score = compute_replant_priority(failure, batch)
    towers_needed = batch.get("tower_count_pin") or len(active_allocations_of_batch(batch["id"]))
    replant = stamp_new({
        "failure_id": failure["id"],
        "priority_score": score,
        "towers_needed": towers_needed,
        "replant_status": "QUEUED",
    })
    store.replant_requests[replant["id"]] = replant
    failure["report_status"] = "REPLANT_REQUESTED"
    touch(failure)
    return success(ser_replant(replant), status=201)


@bp.post("/failure-reports/<fid>/close")
def close_failure(fid):
    require_roles("Grower")
    get_body_optional(set())
    failure = get_failure(fid)
    if failure["report_status"] not in ("TRIAGED", "REPLANT_REQUESTED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Failure not TRIAGED/REPLANT_REQUESTED")
    if failure["report_status"] == "REPLANT_REQUESTED":
        for r in store.replant_requests.values():
            if r["failure_id"] == fid and r["replant_status"] == "QUEUED":
                raise_error("ERR_REPLANT_STILL_QUEUED", "Replant still queued")
    failure["report_status"] = "CLOSED"
    touch(failure)
    return success(ser_failure(failure))


@bp.get("/failure-reports/<fid>/replant-requests")
def list_failure_replants(fid):
    require_roles(*ALL_ROLES)
    failure = get_failure(fid)
    limit, offset = pagination_params()
    items = [r for r in store.replant_requests.values() if r["failure_id"] == failure["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(items, ser_replant, limit, offset)


# ---------------------------------------------------------------- replant requests
@bp.get("/replant-requests")
def list_replants():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.replant_requests.values())
    st = _q("replant_status")
    if st is not None:
        items = [r for r in items if r["replant_status"] == st]
    # QUEUED listing ordered by priority_score DESC, ties by FailureReport.created_at ASC (never id)
    def sort_key(r):
        f = store.failure_reports.get(r["failure_id"])
        f_created = f["created_at"] if f is not None else r["created_at"]
        return (-Decimal(str(r["priority_score"])), f_created)
    items.sort(key=sort_key)
    return list_response(items, ser_replant, limit, offset)


@bp.get("/replant-requests/<rid>")
def get_replant_route(rid):
    require_roles(*ALL_ROLES)
    return success(ser_replant(get_replant(rid)))


@bp.post("/replant-requests/<rid>/approve")
def approve_replant(rid):
    require_roles("FarmManager")
    get_body_optional(set())
    replant = get_replant(rid)
    if replant["replant_status"] != "QUEUED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Replant not QUEUED")
    failure = get_failure(replant["failure_id"])
    failed_batch = get_batch(failure["batch_id"])
    crop = store.crops.get(failed_batch["crop_id"])
    if crop is None:
        raise_error("ERR_NOT_FOUND", "Crop not found")
    if crop["crop_status"] != "ACTIVE":
        raise_error("ERR_CROP_RETIRED", "Crop is RETIRED")
    active_recipe = None
    for r in store.recipes.values():
        if r["crop_id"] == crop["id"] and r["recipe_status"] == "ACTIVE":
            active_recipe = r
            break
    if active_recipe is None:
        raise_error("ERR_NO_ACTIVE_RECIPE", "No ACTIVE recipe")
    towers = select_towers_for_replant(replant["towers_needed"], active_recipe["days_to_harvest"])
    if towers is None:
        raise_error("ERR_REPLANT_NO_TOWERS", "No candidate rack with enough eligible towers")
    now = logical_now()
    # create the replacement batch
    batch = stamp_new({
        "crop_id": crop["id"],
        "recipe_id": active_recipe["id"],
        "origin_replant_request_id": replant["id"],
        "production_status": "PLANNED",
        "safety_status": "PENDING",
        "seeded_at": None,
        "germination_rate_pct": None,
        "yield_factor": Decimal("1.00"),
        "replant_recommended": False,
        "stress_extension_days": 0,
        "projected_harvest_at": None,
        "projected_yield_lb": None,
        "harvested_at": None,
        "harvested_by_user_id": None,
        "grade_a_lb": None, "grade_b_lb": None, "cull_lb": None,
        "harvested_total_lb": None,
        "packed_available_lb": Decimal("0"),
        "packed_lb": Decimal("0"),
        "reserved_lb": Decimal("0"),
        "actual_cost_per_pound_cents": None,
        "tower_count_pin": len(towers),
    })
    store.batches[batch["id"]] = batch
    batch["projected_yield_lb"] = q2(
        Decimal(len(towers)) * Decimal(str(active_recipe["expected_yield_lb_per_tower"]))
    )
    from_at = now
    to_at = now + timedelta(days=active_recipe["days_to_harvest"])
    racks_touched = {}
    for t in towers:
        alloc = stamp_new({
            "batch_id": batch["id"], "tower_id": t["id"],
            "occupied_from_at": from_at, "occupied_to_at": to_at,
            "allocation_status": "ACTIVE",
        })
        store.allocations[alloc["id"]] = alloc
        rack = store.racks[t["rack_id"]]
        rack["occupied_towers"] = rack.get("occupied_towers", 0) + 1
        racks_touched[rack["id"]] = rack
    for rack in racks_touched.values():
        touch(rack)
    replant["replant_status"] = "CONVERTED"
    touch(replant)
    return success(ser_replant(replant))


@bp.post("/replant-requests/<rid>/drop")
def drop_replant(rid):
    require_roles("FarmManager")
    get_body_optional(set())
    replant = get_replant(rid)
    if replant["replant_status"] != "QUEUED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Replant not QUEUED")
    replant["replant_status"] = "DROPPED"
    touch(replant)
    return success(ser_replant(replant))


@bp.get("/replant-requests/<rid>/batches")
def list_replant_batches(rid):
    require_roles(*ALL_ROLES)
    replant = get_replant(rid)
    limit, offset = pagination_params()
    items = [b for b in store.batches.values() if b.get("origin_replant_request_id") == replant["id"]]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    return list_response(items, ser_batch, limit, offset)
