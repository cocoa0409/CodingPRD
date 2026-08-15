"""Batch endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, parse_iso_datetime, make_entity, touch, lookup,
    list_response, public, iso_z,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_LINE_SCHEDULE_OVERLAP, ERR_LINE_NOT_AVAILABLE,
    ERR_ALLERGEN_SEGREGATION_VIOLATION, ERR_PROOF_WINDOW_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES, ERR_NOT_FOUND,
)
from services.calculations import compute_fresh_until, parse_iso_z
from services.cascades import cascade_batch_rejected

bp = Blueprint("batches", __name__)

ACTIVE_BATCH_STATES = ("SCHEDULED", "MIXING", "PROOFING", "BAKING", "COOLING", "OVERPROOFED")


def _serialize(batch):
    return dict(batch)


@bp.route("/bakery/batches", methods=["POST"])
def create_batch():
    _, role = get_auth()
    require_role(role, {"Planner"})
    data = body()
    production_plan_id = req_string(data, "production_plan_id")
    plan = lookup(DB.production_plans, production_plan_id, "production plan")
    line_id = req_string(data, "line_id")
    line = lookup(DB.lines, line_id, "line")
    product_id = req_string(data, "product_id")
    product = lookup(DB.products, product_id, "product")
    qty_units = req_int(data, "qty_units", min_value=1)
    scheduled_start_at = req_string(data, "scheduled_start_at")
    scheduled_end_at = req_string(data, "scheduled_end_at")
    start_dt = parse_iso_datetime(scheduled_start_at, "scheduled_start_at")
    end_dt = parse_iso_datetime(scheduled_end_at, "scheduled_end_at")
    if end_dt <= start_dt:
        raise ApiError(ERR_INVALID_REQUEST, "scheduled_end_at must be after scheduled_start_at", 400)
    if "expected_production_plan_version" not in data:
        raise ApiError(ERR_INVALID_REQUEST, "expected_production_plan_version is required", 400)
    expected = data["expected_production_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_production_plan_version must be an integer", 400)

    # OCC
    if expected != plan.get("version"):
        raise ApiError(ERR_STALE_VERSION, "Stale plan version", 412)

    # State: plan LOCKED or RELEASED
    if plan.get("status") not in ("LOCKED", "RELEASED"):
        raise ApiError(ERR_INVALID_STATE, "Plan must be LOCKED or RELEASED", 409)

    # Safety and duty checks (§2.9 step 7): allergen segregation on a DIRTY line
    if line.get("cleanliness") == "DIRTY":
        if line.get("allergen_class_current") != product.get("allergen_class"):
            raise ApiError(
                ERR_ALLERGEN_SEGREGATION_VIOLATION,
                "Batch allergen class differs from DIRTY line residue class",
                409,
            )

    # Temporal windows (§2.9 step 8): line schedule overlap (half-open)
    for other in DB.batches.values():
        if other.get("line_id") != line_id:
            continue
        if other.get("status") not in ACTIVE_BATCH_STATES:
            continue
        o_start = parse_iso_z(other["scheduled_start_at"])
        o_end = parse_iso_z(other["scheduled_end_at"])
        if start_dt < o_end and end_dt > o_start:
            raise ApiError(ERR_LINE_SCHEDULE_OVERLAP, "Batch window overlaps another batch on this line", 409)

    # Referenced-entity state (§2.9 step 9): line sanitizing
    if line.get("cleanliness") == "SANITIZING":
        raise ApiError(ERR_LINE_NOT_AVAILABLE, "Line is SANITIZING", 409)

    # Caps (§2.9 step 10): qty within batch capacity
    if qty_units > int(product["batch_capacity_units"]):
        raise ApiError(ERR_INVALID_REQUEST, "qty_units exceeds product batch_capacity_units", 400)

    batch = make_entity({
        "production_plan_id": production_plan_id,
        "line_id": line_id,
        "product_id": product_id,
        "qty_units": qty_units,
        "scheduled_start_at": iso_z(start_dt),
        "scheduled_end_at": iso_z(end_dt),
        "status": "SCHEDULED",
        "mix_started_at": None,
        "proof_started_at": None,
        "bake_completed_at": None,
        "completed_by_user_id": None,
        "fresh_until": None,
    })
    DB.batches[batch["id"]] = batch
    touch(plan)
    return success_object(_serialize(batch), status=201)


@bp.route("/bakery/batches/<bid>", methods=["GET"])
def get_batch(bid):
    get_auth()
    batch = lookup(DB.batches, bid, "batch")
    return success_object(_serialize(batch))


@bp.route("/bakery/batches", methods=["GET"])
def list_batches():
    get_auth()
    filters = {
        "production_plan_id": request.args.get("production_plan_id"),
        "line_id": request.args.get("line_id"),
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    return list_response([_serialize(b) for b in DB.batches.values()], filters)


@bp.route("/bakery/batches/<bid>/start-mix", methods=["POST"])
def start_mix(bid):
    _, role = get_auth()
    require_role(role, {"LineOperator"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Batch is not SCHEDULED", 409)
    plan = DB.production_plans.get(batch.get("production_plan_id"))
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "plan not found", 404)
    if plan.get("status") != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, "Plan is not RELEASED", 409)
    batch["status"] = "MIXING"
    batch["mix_started_at"] = DB.clock_iso()
    touch(batch)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/start-proof", methods=["POST"])
def start_proof(bid):
    _, role = get_auth()
    require_role(role, {"LineOperator"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "MIXING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not MIXING", 409)
    batch["status"] = "PROOFING"
    batch["proof_started_at"] = DB.clock_iso()
    touch(batch)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/start-bake", methods=["POST"])
def start_bake(bid):
    _, role = get_auth()
    require_role(role, {"LineOperator"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "PROOFING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not PROOFING", 409)
    proof_dt = parse_iso_z(batch["proof_started_at"])
    elapsed_min = (DB.clock - proof_dt).total_seconds() / 60.0
    if elapsed_min < 60 or elapsed_min > 120:
        raise ApiError(ERR_PROOF_WINDOW_VIOLATION, "start-bake outside 60..120 minute proof window", 409)
    batch["status"] = "BAKING"
    touch(batch)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/complete-bake", methods=["POST"])
def complete_bake(bid):
    user_id, role = get_auth()
    require_role(role, {"LineOperator"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "BAKING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not BAKING", 409)
    product = DB.products.get(batch["product_id"])
    if product is None:
        raise ApiError(ERR_NOT_FOUND, "product not found", 404)
    line = DB.lines.get(batch["line_id"])
    if line is None:
        raise ApiError(ERR_NOT_FOUND, "line not found", 404)

    batch["status"] = "COOLING"
    batch["bake_completed_at"] = DB.clock_iso()
    batch["completed_by_user_id"] = user_id
    fresh_until_dt = compute_fresh_until(DB.clock, int(product["shelf_life_hours"]))
    batch["fresh_until"] = iso_z(fresh_until_dt)
    touch(batch)

    # Line rewrite
    line["allergen_class_current"] = product["allergen_class"]
    if product["allergen_class"] != "NONE":
        line["cleanliness"] = "DIRTY"
    touch(line)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/release", methods=["POST"])
def release_batch(bid):
    user_id, role = get_auth()
    require_role(role, {"QALead"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "COOLING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not COOLING", 409)
    if user_id == batch.get("completed_by_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Releaser must differ from baker", 403)
    batch["status"] = "RELEASED"
    touch(batch)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/reject", methods=["POST"])
def reject_batch(bid):
    _, role = get_auth()
    require_role(role, {"QALead"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") not in ("MIXING", "PROOFING", "BAKING", "COOLING", "OVERPROOFED", "RELEASED"):
        raise ApiError(ERR_INVALID_STATE, "Batch cannot be rejected from this state", 409)
    batch["status"] = "REJECTED"
    touch(batch)
    cascade_batch_rejected(batch)
    return success_object(_serialize(batch))


@bp.route("/bakery/batches/<bid>/abort", methods=["POST"])
def abort_batch(bid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    batch = lookup(DB.batches, bid, "batch")
    if batch.get("status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Batch is not SCHEDULED", 409)
    batch["status"] = "ABORTED"
    touch(batch)
    return success_object(_serialize(batch))
