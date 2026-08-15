"""MenuItem (PRD 3.2, 3.3, 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SAFETY_VIOLATION,
    ERR_BATCH_EXPIRED, ERR_REFERENCE_INVALID, ERR_CAPACITY_FULL, ERR_NOT_FOUND,
)
from helpers import (
    get_body, req_field, req_int, opt_enum, opt_list, check_enum_subset,
    stamp_new, paginate, apply_filters, get_or_404, touch, new_id, now_ts,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list
from services import core

bp = Blueprint("menu_items", __name__)

KM = ["KitchenManager"]
ALL = ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer", "Volunteer", "Guest"]

ALLERGENS = {"GLUTEN", "DAIRY", "EGG", "SOY", "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME"}
DIETARY = {"VEGETARIAN", "VEGAN", "HALAL", "KOSHER_STYLE", "LOW_SODIUM", "DIABETIC_FRIENDLY"}
EQUIP_CLASSES = {"OVEN", "STOVETOP", "COLD_HOLDING", "NONE"}


@bp.route("/kitchen/menu-days/<mid>/menu-items", methods=["POST"])
def create_menu_item(mid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    md = get_or_404("menu_days", mid)

    name = req_field(body, "name", str)
    planned_servings = req_int(body, "planned_servings", minimum=1)
    allergen_tags = opt_list(body, "allergen_tags", [])
    dietary_labels = opt_list(body, "dietary_labels", [])
    check_enum_subset(allergen_tags, ALLERGENS, "allergen_tags")
    check_enum_subset(dietary_labels, DIETARY, "dietary_labels")
    requires_equipment_class = opt_enum(body, "requires_equipment_class", EQUIP_CLASSES, "NONE")

    if md["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "items may only be added while the MenuDay is DRAFT")

    rec = stamp_new({
        "menu_day_id": mid,
        "name": name,
        "planned_servings": planned_servings,
        "allergen_tags": allergen_tags,
        "dietary_labels": dietary_labels,
        "requires_equipment_class": requires_equipment_class,
        "status": "PLANNED",
        "was_confirmed": False,
    })
    db["menu_items"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/kitchen/menu-items/<iid>", methods=["GET"])
def get_menu_item(iid):
    caller = get_caller()
    check_role_allowed(caller, ALL)
    rec = get_or_404("menu_items", iid)
    out = public(rec)
    out.pop("was_confirmed", None)
    return success_object(out)


@bp.route("/kitchen/menu-items/<iid>/batch-allocations", methods=["GET"])
def list_item_allocations(iid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    get_or_404("menu_items", iid)
    items = [a for a in db["batch_allocations"].values()
             if a["menu_item_id"] == iid and not a.get("released")]
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-items/<iid>/meal-orders", methods=["GET"])
def list_item_orders(iid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("menu_items", iid)
    items = [o for o in db["meal_orders"].values() if o["menu_item_id"] == iid]
    items = apply_filters(items, request.args, ["fulfillment_status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-items/<iid>/allocations", methods=["POST"])
def create_allocation(iid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    item = get_or_404("menu_items", iid)

    food_batch_id = req_field(body, "food_batch_id", str)
    servings = req_int(body, "servings", minimum=1)

    batch = db["food_batches"].get(food_batch_id)
    if batch is None:
        raise_error(ERR_NOT_FOUND, f"food batch not found: {food_batch_id}")

    # Priority 5 safety: expired batch
    if not core.batch_not_expired(batch):
        raise_error(ERR_BATCH_EXPIRED, "batch is expired (now >= use_by)")
    # Failed inspection trips safety; other non-ACCEPTED statuses trip reference.
    if batch.get("inspection_result") == "FAILED":
        raise_error(ERR_SAFETY_VIOLATION, "batch failed inspection")
    if batch["status"] != "ACCEPTED":
        raise_error(ERR_REFERENCE_INVALID, f"batch must be ACCEPTED, is {batch['status']}")

    # Priority 9 ceilings: batch remainder, rescue cap. No silent clamp on
    # requested > remaining; explicit rejection.
    if servings > batch["remaining_servings"]:
        raise_error(ERR_CAPACITY_FULL, "requested servings exceed batch remaining_servings")
    if batch["source_type"] == "RESCUE":
        already_for_item = sum(
            a["servings"] for a in db["batch_allocations"].values()
            if a["menu_item_id"] == iid and a["food_batch_id"] == food_batch_id
            and not a.get("released")
        )
        cap = int(batch["quantity_servings"] * 0.5)
        if already_for_item + servings > cap:
            raise_error(ERR_CAPACITY_FULL, "RESCUE cap exceeded for a single MenuItem")

    # Bounded also by uncovered need: allowed = min(requested, remaining, need, cap).
    already = sum(
        a["servings"] for a in db["batch_allocations"].values()
        if a["menu_item_id"] == iid and not a.get("released")
    )
    need = max(0, item["planned_servings"] - already)
    allowed = min(servings, batch["remaining_servings"], need)
    if allowed < 1:
        raise_error(ERR_CAPACITY_FULL, "item is already fully covered")

    rec = {
        "id": new_id(),
        "menu_item_id": iid,
        "food_batch_id": food_batch_id,
        "servings": allowed,
        "allocated_at": now_ts(),
        "created_at": now_ts(),
        "released": False,
    }
    db["batch_allocations"][rec["id"]] = rec
    core.recalc_batch_remaining(batch)
    return success_object(public(rec), 201)


@bp.route("/kitchen/menu-items/<iid>/confirm", methods=["POST"])
def confirm_item(iid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    item = get_or_404("menu_items", iid)

    if item["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, f"cannot confirm from {item['status']}")
    md = db["menu_days"].get(item["menu_day_id"])
    if md is None or md["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "MenuDay must be DRAFT to confirm an item")

    # Coverage gate (state legality)
    covered = sum(
        a["servings"] for a in db["batch_allocations"].values()
        if a["menu_item_id"] == iid and not a.get("released")
    )
    if covered < item["planned_servings"]:
        raise_error(ERR_INVALID_STATE, "batch allocation coverage is below planned_servings")

    # Provenance gates
    for a in db["batch_allocations"].values():
        if a["menu_item_id"] != iid or a.get("released"):
            continue
        batch = db["food_batches"].get(a["food_batch_id"])
        if batch is None:
            raise_error(ERR_REFERENCE_INVALID, "allocated batch is missing")
        if not core.batch_not_expired(batch):
            raise_error(ERR_BATCH_EXPIRED, "an allocated batch is expired")
        if batch.get("inspection_result") != "PASSED" or batch["status"] != "ACCEPTED":
            raise_error(ERR_SAFETY_VIOLATION,
                        "every allocated batch must have PASSED inspection and be ACCEPTED")

    item["status"] = "CONFIRMED"
    item["was_confirmed"] = True
    touch(item)

    md["committed_servings"] += item["planned_servings"]
    core.bump_menu_day(md)
    return success_object(public(item))


@bp.route("/kitchen/menu-items/<iid>/mark-unavailable", methods=["POST"])
def mark_unavailable(iid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    item = get_or_404("menu_items", iid)
    core.mark_item_unavailable(item)
    return success_object(public(item))
