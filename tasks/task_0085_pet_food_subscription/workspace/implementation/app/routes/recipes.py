"""Recipe catalog endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import require_role
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array, success_object
from app.store import store
from app.utils import is_int, is_nonempty_str, is_number, logical_now_iso, new_id


bp = Blueprint("recipes", __name__)


VALID_SPECIES = {"DOG", "CAT"}
VALID_LIFE_STAGE = {"PUPPY_KITTEN", "ADULT", "SENIOR", "ALL"}
VALID_HEALTH = {"KIDNEY", "DIABETES", "DENTAL"}


def _arr(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise api_error("ERR_INVALID_REQUEST", f"{field} must be array of strings")
    return list(value)


@bp.route("/recipes", methods=["POST"])
@require_role("AdminOps")
def create_recipe(user_id: str, role: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    code = body.get("code")
    species = body.get("target_species")
    life_stage = body.get("target_life_stage")
    kcal = body.get("kcal_per_gram")
    unit_price = body.get("unit_price_cents_per_100g")
    monotony = body.get("monotony_class")

    if not is_nonempty_str(code):
        raise api_error("ERR_INVALID_REQUEST", "code required")
    if species not in VALID_SPECIES:
        raise api_error("ERR_INVALID_REQUEST", "target_species invalid")
    if life_stage not in VALID_LIFE_STAGE:
        raise api_error("ERR_INVALID_REQUEST", "target_life_stage invalid")
    if not is_number(kcal) or float(kcal) <= 0 or float(kcal) > 10:
        raise api_error("ERR_INVALID_REQUEST", "kcal_per_gram must be in (0, 10]")
    if not is_int(unit_price) or int(unit_price) < 1:
        raise api_error("ERR_INVALID_REQUEST", "unit_price_cents_per_100g must be integer >= 1")
    if not is_nonempty_str(monotony):
        raise api_error("ERR_INVALID_REQUEST", "monotony_class required")

    proteins = _arr(body.get("protein_sources"), "protein_sources")
    grains = _arr(body.get("grain_sources"), "grain_sources")
    supplements = _arr(body.get("supplement_sources"), "supplement_sources")
    vet_prescribed = bool(body.get("vet_prescribed", False))
    prescribed_for = _arr(body.get("prescribed_for"), "prescribed_for")
    if vet_prescribed:
        if not prescribed_for:
            raise api_error("ERR_INVALID_REQUEST", "prescribed_for required for vet_prescribed")
        for t in prescribed_for:
            if t not in VALID_HEALTH:
                raise api_error("ERR_INVALID_REQUEST", f"invalid prescribed_for: {t}")
    trial_eligible = bool(body.get("trial_eligible", True))

    rid = new_id()
    now = logical_now_iso()
    recipe = {
        "id": rid,
        "created_at": now,
        "code": code,
        "target_species": species,
        "target_life_stage": life_stage,
        "protein_sources": proteins,
        "grain_sources": grains,
        "supplement_sources": supplements,
        "kcal_per_gram": float(kcal),
        "unit_price_cents_per_100g": int(unit_price),
        "vet_prescribed": vet_prescribed,
        "prescribed_for": prescribed_for,
        "monotony_class": monotony,
        "trial_eligible": trial_eligible,
    }
    store.recipes[rid] = recipe
    return success_object(recipe, status=201)


@bp.route("/recipes", methods=["GET"])
@require_role("Customer", "AdminOps")
def list_recipes(user_id: str, role: str):
    limit, offset = parse_pagination()
    items = list(store.recipes.values())
    ts = request.args.get("target_species")
    tls = request.args.get("target_life_stage")
    vp_raw = request.args.get("vet_prescribed")
    if ts:
        items = [r for r in items if r.get("target_species") == ts]
    if tls:
        items = [r for r in items if r.get("target_life_stage") == tls]
    if vp_raw is not None:
        flag = vp_raw.lower() in ("true", "1", "yes")
        items = [r for r in items if bool(r.get("vet_prescribed")) == flag]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/recipes/<recipe_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_recipe(recipe_id, user_id: str, role: str):
    recipe = store.recipes.get(recipe_id)
    if not recipe:
        raise api_error("ERR_RECIPE_NOT_FOUND", "Recipe not found")
    return success_object(recipe)
