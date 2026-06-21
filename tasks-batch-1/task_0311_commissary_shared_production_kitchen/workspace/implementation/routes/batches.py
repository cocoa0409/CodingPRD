"""Production batches: plan, start, complete, scrap."""
from decimal import Decimal

from flask import Blueprint, request

from db import db, LOCK, now_iso
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields, as_int,
)
from services.calculations import (
    estimated_food_cost, actual_food_cost, production_fee, round_half_up,
)

bp = Blueprint("batches", __name__)


def _components_for(recipe_id):
    comps = [c for c in db.recipe_components.values() if c["recipe_id"] == recipe_id]
    return sorted(comps, key=lambda c: c["_seq"])


def _load_member_batch(member_id, batch_id):
    find_member(member_id)
    batch = get_or_404(db.production_batches, batch_id)
    if batch["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return batch


@bp.post("/members/<member_id>/batches")
def create_batch(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        require_fields(body, ["recipe_id", "planned_yield_units"])
        recipe = get_or_404(db.recipes, body["recipe_id"])
        planned_yield = as_int(body["planned_yield_units"])

        # Member active (priority 9).
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE")
        # Recipe PUBLISHED (priority 16).
        if recipe["status"] != "PUBLISHED":
            raise ApiError("ERR_RECIPE_NOT_PUBLISHED")
        # planned_yield_units >= 1.
        if planned_yield < 1:
            raise ApiError("ERR_INVALID_REQUEST")

        comps = _components_for(recipe["id"])
        cost_by_id = {c["ingredient_id"]: db.ingredients[c["ingredient_id"]]["unit_cost_cents"]
                      for c in comps}
        scale = Decimal(planned_yield) / Decimal(recipe["batch_yield_units"])
        est = estimated_food_cost(comps, cost_by_id, scale)

        batch = {
            "member_id": member_id,
            "recipe_id": recipe["id"],
            "recipe_version_pinned": recipe["version"],
            "planned_yield_units": planned_yield,
            "actual_yield_units": None,
            "estimated_food_cost_cents": est,
            "actual_food_cost_cents": None,
            "production_fee_cents": None,
            "actual_components": [],
            "status": "PLANNED",
            "_completed_at": None,
        }
        stamp_new(batch)
        db.production_batches[batch["id"]] = batch
        return success(public(batch), 201)


@bp.get("/members/<member_id>/batches")
def list_member_batches(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    recipe_id = request.args.get("recipe_id")
    with LOCK:
        find_member(member_id)
        records = [b for b in db.production_batches.values() if b["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [b for b in records if b["status"] == status]
        if recipe_id:
            records = [b for b in records if b["recipe_id"] == recipe_id]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/batches/<batch_id>")
def get_member_batch(member_id, batch_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        batch = _load_member_batch(member_id, batch_id)
        return success(public(batch))


@bp.post("/members/<member_id>/batches/<batch_id>/start")
def start_batch(member_id, batch_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        batch = _load_member_batch(member_id, batch_id)
        if batch["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_STATE")
        recipe = db.recipes[batch["recipe_id"]]
        comps = _components_for(recipe["id"])
        scale = Decimal(batch["planned_yield_units"]) / Decimal(recipe["batch_yield_units"])
        for c in comps:
            ing = db.ingredients[c["ingredient_id"]]
            demand = Decimal(str(c["planned_qty"])) * scale
            if Decimal(str(ing["on_hand_qty"])) < demand:
                raise ApiError("ERR_INSUFFICIENT_STOCK")
        batch["status"] = "IN_PRODUCTION"
        touch(batch)
        return success(public(batch))


@bp.post("/members/<member_id>/batches/<batch_id>/complete")
def complete_batch(member_id, batch_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        batch = _load_member_batch(member_id, batch_id)
        require_fields(body, ["actual_yield_units"])
        actual_yield = as_int(body["actual_yield_units"])

        if batch["status"] != "IN_PRODUCTION":
            raise ApiError("ERR_INVALID_STATE")
        if actual_yield < 1:
            raise ApiError("ERR_INVALID_REQUEST")

        member = db.members[member_id]
        recipe = db.recipes[batch["recipe_id"]]
        comps = _components_for(recipe["id"])
        scale = Decimal(batch["planned_yield_units"]) / Decimal(recipe["batch_yield_units"])

        # Build the actual consumption per BOM ingredient: supplied actuals
        # override the scaled planned default for omitted ingredients.
        supplied = {}
        provided = body.get("actual_components") or []
        if not isinstance(provided, list):
            raise ApiError("ERR_INVALID_REQUEST")
        for entry in provided:
            if not isinstance(entry, dict) or "ingredient_id" not in entry or "actual_qty" not in entry:
                raise ApiError("ERR_INVALID_REQUEST")
            supplied[entry["ingredient_id"]] = entry["actual_qty"]

        actual_lines = []
        cost_by_id = {}
        for c in comps:
            ing = db.ingredients[c["ingredient_id"]]
            cost_by_id[c["ingredient_id"]] = ing["unit_cost_cents"]
            if c["ingredient_id"] in supplied:
                qty = supplied[c["ingredient_id"]]
            else:
                qty = float(Decimal(str(c["planned_qty"])) * scale)
            actual_lines.append({"ingredient_id": c["ingredient_id"], "actual_qty": qty})

        afc, _base, _spoil = actual_food_cost(actual_lines, cost_by_id)
        fee = production_fee(actual_yield)

        # Wallet sufficiency against the production fee (priority 22).
        if member["wallet_balance_cents"] < fee:
            raise ApiError("ERR_INSUFFICIENT_WALLET")

        # Commit: charge wallet, draw down inventory, record actuals.
        batch["actual_yield_units"] = actual_yield
        batch["actual_components"] = actual_lines
        batch["actual_food_cost_cents"] = afc
        batch["production_fee_cents"] = fee
        batch["status"] = "COMPLETED"
        batch["_completed_at"] = now_iso()
        touch(batch)

        for line in actual_lines:
            ing = db.ingredients[line["ingredient_id"]]
            new_qty = Decimal(str(ing["on_hand_qty"])) - Decimal(str(line["actual_qty"]))
            ing["on_hand_qty"] = _normalize_qty(new_qty)
            touch(ing)

        member["wallet_balance_cents"] -= fee
        member["lifetime_charged_cents"] += fee
        touch(member)

        return success(public(batch))


def _normalize_qty(dec_value):
    """Return an int when the quantity is integral, else a float."""
    if dec_value == dec_value.to_integral_value():
        return int(dec_value)
    return float(dec_value)


@bp.post("/members/<member_id>/batches/<batch_id>/scrap")
def scrap_batch(member_id, batch_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        batch = _load_member_batch(member_id, batch_id)
        if batch["status"] not in ("PLANNED", "IN_PRODUCTION"):
            raise ApiError("ERR_INVALID_STATE")
        batch["status"] = "SCRAPPED"
        touch(batch)
        return success(public(batch))
