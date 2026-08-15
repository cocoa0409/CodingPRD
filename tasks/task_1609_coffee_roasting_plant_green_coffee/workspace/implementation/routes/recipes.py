"""Blend recipe governance: create, components, approve (OCC), retire (PRD §3.7)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_RECIPE_COMPONENT_SUM_INVALID,
    ERR_STALE_VERSION, ERR_SUBSTITUTION_RULE_INVALID, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body,
    occ_value, paginate, pub, require_fields, require_role, sort_created,
    touch, v_enum, v_int, v_num,
)
from response import success_list, success_object

bp = Blueprint("recipes", __name__)

GRADES = {"SHB", "HG", "NY2_3", "ROBUSTA_GRADE1"}
READ_ROLES = ("HeadRoaster", "RoastOperator")

RECIPE_CREATE_ALLOWED = {
    "product_id", "recipe_version", "recipe_status", "approved_at",
} | COMMON_SYS

COMPONENT_ALLOWED = {
    "required_grade", "component_pct", "substitution_grade", "substitution_max_pct",
    "recipe_id",
} | COMMON_SYS

APPROVE_ALLOWED = {"expected_product_version"} | COMMON_SYS | {
    "product_id", "recipe_version", "recipe_status", "approved_at"}


def get_recipe_or_404(recipe_id):
    r = DB.recipes.get(recipe_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipe id does not exist")
    return r


def _substitution_consistency(required_grade, sub_grade, sub_max, enforce_max_positive=False):
    """ERR_SUBSTITUTION_RULE_INVALID when the substitution pair is inconsistent."""
    if (sub_grade is None) != (sub_max is None):
        raise err(ERR_SUBSTITUTION_RULE_INVALID,
                  "substitution_grade non-null iff substitution_max_pct non-null")
    if sub_grade is not None:
        if sub_grade == required_grade:
            raise err(ERR_SUBSTITUTION_RULE_INVALID,
                      "substitution_grade must differ from required_grade")
        if enforce_max_positive and not (D(sub_max) > 0 and D(sub_max) <= 1):
            raise err(ERR_SUBSTITUTION_RULE_INVALID,
                      "substitution_max_pct must be in (0, 1]")


@bp.post("/roastery/products/<product_id>/recipes")
def create_recipe(product_id):
    require_role("HeadRoaster")
    product = DB.products.get(product_id)
    if product is None:
        raise err(ERR_NOT_FOUND, "Product id does not exist")
    body = get_json_body()
    check_unknown_fields(body, RECIPE_CREATE_ALLOWED)
    existing = [r for r in DB.recipes.values() if r["product_id"] == product_id]
    next_version = 1 + max((r["recipe_version"] for r in existing), default=0)
    r = base_fields()
    r.update({
        "product_id": product_id,
        "recipe_version": next_version,
        "recipe_status": "DRAFT",
        "approved_at": None,
    })
    DB.recipes[r["id"]] = r
    return success_object(pub(r), status=201)


@bp.get("/roastery/recipes/<recipe_id>")
def get_recipe(recipe_id):
    require_role(*READ_ROLES)
    return success_object(pub(get_recipe_or_404(recipe_id)))


@bp.get("/roastery/products/<product_id>/recipes")
def list_recipes(product_id):
    require_role(*READ_ROLES)
    if product_id not in DB.products:
        raise err(ERR_NOT_FOUND, "Product id does not exist")
    items = sort_created(
        [r for r in DB.recipes.values() if r["product_id"] == product_id])
    status = request.args.get("recipe_status")
    if status is not None:
        items = [r for r in items if r["recipe_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(r) for r in page], limit, offset, total)


@bp.post("/roastery/recipes/<recipe_id>/components")
def add_component(recipe_id):
    require_role("HeadRoaster")
    recipe = get_recipe_or_404(recipe_id)
    body = get_json_body()

    # Priority 6: components may only be added to a DRAFT recipe.
    if recipe["recipe_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Components may only be added to a DRAFT recipe")

    # Priority 11: substitution-pair consistency (evaluated on raw values).
    _substitution_consistency(
        body.get("required_grade"), body.get("substitution_grade"),
        body.get("substitution_max_pct"))

    # Priorities 22/23: structural.
    check_unknown_fields(body, COMPONENT_ALLOWED)
    require_fields(body, ["required_grade", "component_pct"])
    grade = v_enum(body, "required_grade", GRADES)
    pct = v_num(body, "component_pct", gt=0, le=1)
    sub_grade = v_enum(body, "substitution_grade", GRADES, required=False)
    sub_max = v_num(body, "substitution_max_pct", ge=0, le=1, required=False)
    _substitution_consistency(grade, sub_grade, sub_max)

    c = base_fields()
    c.update({
        "recipe_id": recipe_id,
        "required_grade": grade,
        "component_pct": pct,
        "substitution_grade": sub_grade,
        "substitution_max_pct": sub_max,
    })
    DB.recipe_components[c["id"]] = c
    return success_object(pub(c), status=201)


@bp.get("/roastery/recipes/<recipe_id>/components")
def list_components(recipe_id):
    require_role(*READ_ROLES)
    get_recipe_or_404(recipe_id)
    items = sort_created(
        [c for c in DB.recipe_components.values() if c["recipe_id"] == recipe_id])
    page, limit, offset, total = paginate(items)
    return success_list([pub(c) for c in page], limit, offset, total)


@bp.post("/roastery/recipes/<recipe_id>/approve")
def approve_recipe(recipe_id):
    require_role("HeadRoaster")
    recipe = get_recipe_or_404(recipe_id)
    body = get_json_body()
    product = DB.products.get(recipe["product_id"])

    # Priority 6: state.
    if recipe["recipe_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Approve requires recipe_status DRAFT")

    # Priority 7: OCC against the parent product.
    present, val = occ_value(body, "expected_product_version")
    if present and (val is None or product is None or val != product["version"]):
        raise err(ERR_STALE_VERSION,
                  "expected_product_version does not match current product version")

    # Priority 10: component percentages must sum to exactly 1.00000.
    comps = [c for c in DB.recipe_components.values() if c["recipe_id"] == recipe_id]
    total = sum((D(c["component_pct"]) for c in comps), Decimal(0))
    if total.quantize(Decimal("0.00001")) != Decimal("1.00000"):
        raise err(ERR_RECIPE_COMPONENT_SUM_INVALID,
                  "Recipe component_pct values must sum to exactly 1.00000")

    # Priority 11: substitution consistency across every component.
    for c in comps:
        _substitution_consistency(
            c["required_grade"], c.get("substitution_grade"),
            c.get("substitution_max_pct"), enforce_max_positive=True)

    # Priorities 22/23: structural (the OCC field is non-optional per PRD §2.9).
    check_unknown_fields(body, APPROVE_ALLOWED)
    require_fields(body, ["expected_product_version"])
    v_int(body, "expected_product_version")

    from clock import now_iso
    recipe["recipe_status"] = "APPROVED"
    recipe["approved_at"] = now_iso()
    touch(recipe)
    # Any previously APPROVED recipe for this product is superseded.
    for other in DB.recipes.values():
        if (other["product_id"] == recipe["product_id"]
                and other["id"] != recipe["id"]
                and other["recipe_status"] == "APPROVED"):
            other["recipe_status"] = "SUPERSEDED"
            touch(other)
    if product is not None:
        touch(product)
    return success_object(pub(recipe))


@bp.post("/roastery/recipes/<recipe_id>/retire")
def retire_recipe(recipe_id):
    require_role("HeadRoaster")
    recipe = get_recipe_or_404(recipe_id)
    get_json_body()
    if recipe["recipe_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Retire requires recipe_status DRAFT")
    if any(b["recipe_id"] == recipe_id for b in DB.roast_batches.values()):
        raise err(ERR_INVALID_STATE, "Retire blocked: a roast batch references this recipe")
    recipe["recipe_status"] = "RETIRED"
    touch(recipe)
    return success_object(pub(recipe))
