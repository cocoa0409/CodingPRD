from flask import Blueprint, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import get_or_404
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, req_num, req_str

bp = Blueprint("reworks", __name__)


@bp.post("/qa/rework-batches")
@require_roles("LineOperator", "QaSupervisor")
def create_batch():
    b = body()
    source_run = get_or_404("runs", req_str(b, "source_run_id"))
    source_product = get_or_404("products", req_str(b, "source_product_id"))
    quantity = req_num(b, "quantity_kg")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "quantity_kg must be greater than 0")
    ent = new_entity({
        "source_run_id": source_run["id"],
        "source_product_id": source_product["id"],
        "quantity_kg": quantity,
        "remaining_kg": quantity,
        "rework_allergen_set": list(source_product["allergen_set"]),
        "status": "AVAILABLE",
    })
    db["reworks"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/rework-batches")
@require_roles(*ALL_ROLES)
def list_batches():
    items = list(db["reworks"].values())
    for param in ("source_run_id", "source_product_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return ok_list(items)


@bp.get("/qa/rework-batches/<batchId>")
@require_roles(*ALL_ROLES)
def get_batch(batchId):
    return ok(public(get_or_404("reworks", batchId)))


@bp.post("/qa/rework-batches/<batchId>/commit")
@require_roles("LineOperator")
def commit_batch(batchId):
    batch = get_or_404("reworks", batchId)
    b = body()
    target_run = get_or_404("runs", req_str(b, "target_run_id"))
    quantity = req_num(b, "quantity_kg")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "quantity_kg must be greater than 0")
    if batch["status"] != "AVAILABLE":
        raise ApiError("ERR_REWORK_NOT_AVAILABLE", 409,
                       "Rework batch is not AVAILABLE")
    if batch["remaining_kg"] <= 0 or quantity > batch["remaining_kg"]:
        raise ApiError("ERR_REWORK_EXHAUSTED", 422,
                       "Commit quantity exceeds remaining_kg")
    tgt_product = get_or_404("products", target_run["product_id"])
    src_set = set(batch["rework_allergen_set"])
    tgt_set = set(tgt_product["allergen_set"])
    cls = tgt_product["rework_class"]
    # Class gate first (pinned order).
    if cls == "SAME_INTO_SAME":
        if batch["source_product_id"] != target_run["product_id"]:
            raise ApiError("ERR_REWORK_CLASS_VIOLATION", 422,
                           "SAME_INTO_SAME requires the same product")
    elif cls == "SAME_ALLERGEN_PROFILE":
        if src_set != tgt_set:
            raise ApiError("ERR_REWORK_CLASS_VIOLATION", 422,
                           "SAME_ALLERGEN_PROFILE requires an identical allergen set")
    elif cls == "RESTRICTED_REWORK":
        if not src_set <= tgt_set:
            raise ApiError("ERR_REWORK_CLASS_VIOLATION", 422,
                           "RESTRICTED_REWORK requires allergen subset")
    elif cls == "NO_REWORK":
        raise ApiError("ERR_REWORK_CLASS_VIOLATION", 422,
                       "NO_REWORK forbids all commits")
    # Allergen containment rule (always).
    if not src_set <= tgt_set:
        raise ApiError("ERR_REWORK_ALLERGEN_BREACH", 422,
                       "rework_allergen_set is not a subset of the target allergen set")
    batch["remaining_kg"] = round(float(batch["remaining_kg"]) - float(quantity), 6)
    if abs(batch["remaining_kg"]) < 1e-9:
        batch["remaining_kg"] = 0
    batch["status"] = "COMMITTED"
    if batch["remaining_kg"] == 0:
        batch["status"] = "CONSUMED"
    touch(batch)
    return ok(public(batch))


@bp.post("/qa/rework-batches/<batchId>/scrap")
@require_roles("QaSupervisor")
def scrap_batch(batchId):
    batch = get_or_404("reworks", batchId)
    if batch["status"] not in ("AVAILABLE", "COMMITTED"):
        raise ApiError("ERR_REWORK_TERMINAL", 409,
                       "Rework batch is CONSUMED or SCRAPPED")
    batch["status"] = "SCRAPPED"
    batch["remaining_kg"] = 0
    touch(batch)
    return ok(public(batch))
