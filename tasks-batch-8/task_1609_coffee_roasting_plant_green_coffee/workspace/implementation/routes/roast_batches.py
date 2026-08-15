"""Roast batch scheduling, allocation, production, and packing (PRD §3.8-3.9)."""

from flask import Blueprint, request

from clock import now_iso
from db import DB
from errors import (
    ERR_INVALID_PACK_QUANTITY, ERR_INVALID_STATE, ERR_INVALID_YIELD,
    ERR_NOT_FOUND, ERR_RECIPE_NOT_APPROVED, err,
)
from middleware import (
    COMMON_SYS, base_fields, check_unknown_fields, get_json_body, is_number,
    paginate, pub, require_fields, require_role, sort_created, touch, v_int,
)
from response import success_list, success_object
from services import (
    compute_yield_fields, maybe_deplete_green_lot, plan_blend_allocation,
    recompute_position, sellable_until_for,
)

bp = Blueprint("roast_batches", __name__)

BATCH_ALLOWED = {
    "product_id", "recipe_id", "scheduled_green_lbs", "production_status",
    "qc_status", "actual_roasted_lbs", "actual_yield_loss_pct",
    "yield_variance_flag", "recipe_version_pinned", "roast_completed_at",
} | COMMON_SYS

FINISH_ALLOWED = {"actual_roasted_lbs"} | COMMON_SYS
PACK_ALLOWED = {"packed_lbs"} | COMMON_SYS

READ_ROLES = ("RoastOperator", "HeadRoaster", "QAGrader")
ALLOC_READ_ROLES = ("RoastOperator", "HeadRoaster")


def get_batch_or_404(batch_id):
    b = DB.roast_batches.get(batch_id)
    if b is None:
        raise err(ERR_NOT_FOUND, "Roast batch id does not exist")
    return b


def serialize_batch(b):
    return pub(b)


@bp.post("/roastery/roast-batches")
def create_roast_batch():
    user_id, _ = require_role("RoastOperator")
    body = get_json_body()

    # Priority 5: body FK existence.
    product_id = body.get("product_id")
    recipe_id = body.get("recipe_id")
    product = DB.products.get(product_id) if isinstance(product_id, str) else None
    recipe = DB.recipes.get(recipe_id) if isinstance(recipe_id, str) else None
    if isinstance(product_id, str) and product is None:
        raise err(ERR_NOT_FOUND, "product_id does not exist")
    if isinstance(recipe_id, str) and recipe is None:
        raise err(ERR_NOT_FOUND, "recipe_id does not exist")

    scheduled_raw = body.get("scheduled_green_lbs")
    scheduled_ok = is_number(scheduled_raw)

    # A recipe that cannot be pinned (not APPROVED, or belongs to another
    # product) is rejected before the allocation waterfall runs: its
    # components never enter inventory planning.
    if recipe is not None and product is not None:
        if recipe["recipe_status"] != "APPROVED" or recipe["product_id"] != product["id"]:
            raise err(ERR_RECIPE_NOT_APPROVED,
                      "Pinned recipe is not APPROVED or does not belong to the product")

    # Green-inventory sufficiency via the allocation waterfall (simulated;
    # nothing persists on failure).
    plan = None
    if recipe is not None and scheduled_ok and int(scheduled_raw) >= 0:
        plan = plan_blend_allocation(recipe, int(scheduled_raw))

    # Priorities 22/23: structural.
    check_unknown_fields(body, BATCH_ALLOWED)
    require_fields(body, ["product_id", "recipe_id", "scheduled_green_lbs"])
    if product is None:
        raise err(ERR_NOT_FOUND, "product_id does not exist")
    if recipe is None:
        raise err(ERR_NOT_FOUND, "recipe_id does not exist")
    scheduled = v_int(body, "scheduled_green_lbs", gt=0)
    if plan is None:
        plan = plan_blend_allocation(recipe, scheduled)

    batch = base_fields()
    batch.update({
        "product_id": product["id"],
        "recipe_id": recipe["id"],
        "scheduled_green_lbs": scheduled,
        "production_status": "SCHEDULED",
        "qc_status": "NOT_REQUIRED",
        "actual_roasted_lbs": None,
        "actual_yield_loss_pct": None,
        "yield_variance_flag": "UNKNOWN",
        "recipe_version_pinned": recipe["recipe_version"],
        "roast_completed_at": None,
        "_operator_ids": {user_id},
    })
    DB.roast_batches[batch["id"]] = batch

    touched_lots = set()
    for step in plan:
        alloc = base_fields()
        alloc.update({
            "roast_batch_id": batch["id"],
            "green_lot_id": step["lot"]["id"],
            "component_id": step["component"]["id"],
            "allocated_lbs": step["take"],
            "is_substitution": step["is_substitution"],
            "allocation_status": "ACTIVE",
        })
        DB.roast_allocations[alloc["id"]] = alloc
        step["lot"]["available_lbs"] -= step["take"]
        touched_lots.add(step["lot"]["id"])
    for lot_id in touched_lots:
        touch(DB.green_lots[lot_id])
    recompute_position()
    return success_object(serialize_batch(batch), status=201)


@bp.get("/roastery/roast-batches/<batch_id>")
def get_roast_batch(batch_id):
    require_role(*READ_ROLES)
    return success_object(serialize_batch(get_batch_or_404(batch_id)))


@bp.get("/roastery/roast-batches")
def list_roast_batches():
    require_role(*READ_ROLES)
    items = sort_created(DB.roast_batches.values())
    product_id = request.args.get("product_id")
    recipe_id = request.args.get("recipe_id")
    ps = request.args.get("production_status")
    qs = request.args.get("qc_status")
    if product_id is not None:
        items = [b for b in items if b["product_id"] == product_id]
    if recipe_id is not None:
        items = [b for b in items if b["recipe_id"] == recipe_id]
    if ps is not None:
        items = [b for b in items if b["production_status"] == ps]
    if qs is not None:
        items = [b for b in items if b["qc_status"] == qs]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_batch(b) for b in page], limit, offset, total)


@bp.get("/roastery/roast-batches/<batch_id>/allocations")
def list_batch_allocations(batch_id):
    require_role(*ALLOC_READ_ROLES)
    get_batch_or_404(batch_id)
    items = sort_created(
        [a for a in DB.roast_allocations.values() if a["roast_batch_id"] == batch_id])
    page, limit, offset, total = paginate(items)
    return success_list([pub(a) for a in page], limit, offset, total)


@bp.get("/roastery/roast-input-allocations/<alloc_id>")
def get_allocation(alloc_id):
    require_role(*ALLOC_READ_ROLES)
    a = DB.roast_allocations.get(alloc_id)
    if a is None:
        raise err(ERR_NOT_FOUND, "Roast input allocation id does not exist")
    return success_object(pub(a))


@bp.get("/roastery/roast-input-allocations")
def list_allocations():
    require_role(*ALLOC_READ_ROLES)
    items = sort_created(DB.roast_allocations.values())
    batch_id = request.args.get("roast_batch_id")
    lot_id = request.args.get("green_lot_id")
    comp_id = request.args.get("component_id")
    status = request.args.get("allocation_status")
    if batch_id is not None:
        items = [a for a in items if a["roast_batch_id"] == batch_id]
    if lot_id is not None:
        items = [a for a in items if a["green_lot_id"] == lot_id]
    if comp_id is not None:
        items = [a for a in items if a["component_id"] == comp_id]
    if status is not None:
        items = [a for a in items if a["allocation_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(a) for a in page], limit, offset, total)


def _batch_allocations(batch_id):
    return [a for a in DB.roast_allocations.values() if a["roast_batch_id"] == batch_id]


@bp.post("/roastery/roast-batches/<batch_id>/start")
def start_batch(batch_id):
    user_id, _ = require_role("RoastOperator")
    batch = get_batch_or_404(batch_id)
    get_json_body()
    if batch["production_status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Start requires production_status SCHEDULED")
    # Stale-recipe guard: pinned recipe must still be APPROVED at its pinned version.
    recipe = DB.recipes.get(batch["recipe_id"])
    if (recipe is None or recipe["recipe_status"] != "APPROVED"
            or recipe["recipe_version"] != batch["recipe_version_pinned"]):
        raise err(ERR_INVALID_STATE,
                  "Pinned recipe is no longer APPROVED at the pinned version (stale recipe)")
    allocs = _batch_allocations(batch_id)
    if any(a["allocation_status"] != "ACTIVE" for a in allocs):
        raise err(ERR_INVALID_STATE, "All roast input allocations must be ACTIVE to start")
    if sum(a["allocated_lbs"] for a in allocs) != batch["scheduled_green_lbs"]:
        raise err(ERR_INVALID_STATE,
                  "Allocations must sum exactly to scheduled_green_lbs")

    touched_lots = set()
    for a in allocs:
        a["allocation_status"] = "CONSUMED"
        touch(a)
        touched_lots.add(a["green_lot_id"])
    for lot_id in touched_lots:
        lot = DB.green_lots.get(lot_id)
        if lot is not None:
            maybe_deplete_green_lot(lot)
    batch["production_status"] = "IN_DRUM"
    batch["_operator_ids"].add(user_id)
    touch(batch)
    recompute_position()
    return success_object(serialize_batch(batch))


@bp.post("/roastery/roast-batches/<batch_id>/finish")
def finish_batch(batch_id):
    user_id, _ = require_role("RoastOperator")
    batch = get_batch_or_404(batch_id)
    body = get_json_body()
    if batch["production_status"] != "IN_DRUM":
        raise err(ERR_INVALID_STATE, "Finish requires production_status IN_DRUM")
    check_unknown_fields(body, FINISH_ALLOWED)
    require_fields(body, ["actual_roasted_lbs"])
    actual = v_int(body, "actual_roasted_lbs")
    # Priority 29: yield sanity — strictly positive, strictly less than input.
    if not (actual > 0) or not (actual < batch["scheduled_green_lbs"]):
        raise err(ERR_INVALID_YIELD,
                  "actual_roasted_lbs must be > 0 and < scheduled_green_lbs")

    batch["actual_roasted_lbs"] = actual
    product = DB.products.get(batch["product_id"])
    loss, flag = compute_yield_fields(batch, product)
    batch["actual_yield_loss_pct"] = loss
    batch["yield_variance_flag"] = flag
    batch["roast_completed_at"] = now_iso()
    batch["production_status"] = "ROASTED"
    batch["qc_status"] = "PENDING_QC"
    batch["_operator_ids"].add(user_id)
    touch(batch)
    return success_object(serialize_batch(batch))


@bp.post("/roastery/roast-batches/<batch_id>/pack")
def pack_batch(batch_id):
    require_role("RoastOperator")
    batch = get_batch_or_404(batch_id)
    body = get_json_body()
    if batch["production_status"] != "ROASTED":
        raise err(ERR_INVALID_STATE, "Pack requires production_status ROASTED")
    if batch["qc_status"] != "QC_PASSED":
        raise err(ERR_INVALID_STATE, "Pack requires qc_status QC_PASSED")
    check_unknown_fields(body, PACK_ALLOWED)
    require_fields(body, ["packed_lbs"])
    packed = v_int(body, "packed_lbs")
    # Priority 24.
    if not (packed > 0) or packed > batch["actual_roasted_lbs"]:
        raise err(ERR_INVALID_PACK_QUANTITY,
                  "packed_lbs must be > 0 and <= actual_roasted_lbs")

    product = DB.products.get(batch["product_id"])
    lot = base_fields()
    lot.update({
        "roast_batch_id": batch["id"],
        "product_id": batch["product_id"],
        "packed_lbs": packed,
        "packed_at": now_iso(),
        "sellable_until": sellable_until_for(batch, product),
        "available_lbs": packed,
        "lot_status": "FRESH",
    })
    DB.finished_goods_lots[lot["id"]] = lot
    batch["production_status"] = "PACKED"
    touch(batch)
    return success_object(pub(lot), status=201)


@bp.post("/roastery/roast-batches/<batch_id>/void")
def void_batch(batch_id):
    require_role("RoastOperator")
    batch = get_batch_or_404(batch_id)
    get_json_body()
    if batch["production_status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Void requires production_status SCHEDULED")
    allocs = _batch_allocations(batch_id)
    touched_lots = set()
    for a in allocs:
        if a["allocation_status"] == "ACTIVE":
            a["allocation_status"] = "RELEASED"
            touch(a)
            lot = DB.green_lots.get(a["green_lot_id"])
            if lot is not None:
                lot["available_lbs"] += a["allocated_lbs"]
                touched_lots.add(lot["id"])
    for lot_id in touched_lots:
        touch(DB.green_lots[lot_id])
    batch["production_status"] = "VOIDED"
    touch(batch)
    recompute_position()
    return success_object(serialize_batch(batch))
