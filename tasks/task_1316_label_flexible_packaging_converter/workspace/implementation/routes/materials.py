"""Substrate and InkRecipe endpoints (PRD 3.1)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_substrate, sorted_created
from util import as_bool, as_int, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("materials", __name__)

_SUBSTRATE_FIELDS = {
    "substrate_code",
    "width_mm",
    "cost_per_msq_cents",
    "food_contact_certified",
}
_RECIPE_FIELDS = {"recipe_code", "food_contact_compliant", "cost_per_lb_cents"}


@bp.post("/label-jobs/substrates")
def create_substrate():
    auth(["Estimator"])
    data = body()
    reject_unknown(data, _SUBSTRATE_FIELDS)
    substrate_code = as_str(required(data, "substrate_code"), "substrate_code")
    width_mm = as_int(required(data, "width_mm"), "width_mm")
    cost_per_msq_cents = as_int(
        required(data, "cost_per_msq_cents"), "cost_per_msq_cents"
    )
    food_contact_certified = (
        as_bool(data["food_contact_certified"], "food_contact_certified")
        if "food_contact_certified" in data
        else False
    )
    ts = now_iso()
    substrate = {
        "id": new_id(),
        "substrate_code": substrate_code,
        "width_mm": width_mm,
        "cost_per_msq_cents": cost_per_msq_cents,
        "food_contact_certified": food_contact_certified,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["substrates"][substrate["id"]] = substrate
    return ok(substrate, 201)


@bp.get("/label-jobs/substrates")
def list_substrates():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["substrates"].values())
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/substrates/<substrate_id>")
def get_one_substrate(substrate_id):
    auth(ALL_ROLES)
    return ok(get_substrate(substrate_id))


@bp.post("/label-jobs/ink-recipes")
def create_ink_recipe():
    auth(["Estimator"])
    data = body()
    reject_unknown(data, _RECIPE_FIELDS)
    recipe_code = as_str(required(data, "recipe_code"), "recipe_code")
    food_contact_compliant = (
        as_bool(data["food_contact_compliant"], "food_contact_compliant")
        if "food_contact_compliant" in data
        else False
    )
    cost_per_lb_cents = as_int(
        required(data, "cost_per_lb_cents"), "cost_per_lb_cents"
    )
    ts = now_iso()
    recipe = {
        "id": new_id(),
        "recipe_code": recipe_code,
        "food_contact_compliant": food_contact_compliant,
        "cost_per_lb_cents": cost_per_lb_cents,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["ink_recipes"][recipe["id"]] = recipe
    return ok(recipe, 201)


@bp.get("/label-jobs/ink-recipes")
def list_ink_recipes():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["ink_recipes"].values())
    return ok_list(items[offset : offset + limit], len(items), limit, offset)
