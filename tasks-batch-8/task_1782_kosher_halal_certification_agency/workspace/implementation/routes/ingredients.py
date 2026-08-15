"""Ingredient endpoints (PRD §3.3): dossier submission, review decisions, and
the cyclic change-notice / re-approval loop."""
from flask import Blueprint

from db import new_common, store, touch
from errors import err
from middleware import get_or_404, require_client_scope, require_roles
from response import Paginator, created, ok
from services.domain import (ingredient_compensation_cascade,
                             ingredient_freeze_cascade)
from validation import body_json, opt_bool, req_enum, req_str

bp = Blueprint("ingredients", __name__)

SOURCE_CATEGORIES = ("ANIMAL", "PLANT", "MICROBIAL", "MINERAL", "SYNTHETIC")


@bp.post("/ingredients")
def create_ingredient():
    data = body_json()
    client_id = req_str(data, "client_id")
    name = req_str(data, "name")
    manufacturer = req_str(data, "manufacturer")
    source_category = req_enum(data, "source_category", SOURCE_CATEGORIES)
    has_species_documentation = opt_bool(data, "has_species_documentation", default=False)
    require_roles("ClientContact")
    require_client_scope(client_id)
    get_or_404(store.clients, client_id, "Client")
    ingredient = new_common({
        "client_id": client_id,
        "name": name,
        "manufacturer": manufacturer,
        "source_category": source_category,
        "has_species_documentation": has_species_documentation,
        "change_summary": None,
        "status": "SUBMITTED",
    })
    store.ingredients[ingredient["id"]] = ingredient
    return created(ingredient)


@bp.get("/ingredients")
def list_ingredients():
    p = Paginator()
    rows = list(store.ingredients.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "status")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/ingredients/<ingredient_id>")
def get_ingredient(ingredient_id):
    return ok(get_or_404(store.ingredients, ingredient_id, "Ingredient"))


@bp.get("/ingredients/<ingredient_id>/product-usages")
def list_ingredient_product_usages(ingredient_id):
    get_or_404(store.ingredients, ingredient_id, "Ingredient")
    p = Paginator()
    rows = [j for j in store.product_ingredients.values()
            if j["ingredient_id"] == ingredient_id]
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/ingredients/<ingredient_id>/start-review")
def start_review(ingredient_id):
    require_roles("CertificationReviewer")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    if ingredient["status"] != "SUBMITTED":
        err("ERR_INGREDIENT_INVALID_STATE",
            "start-review requires ingredient status SUBMITTED")
    ingredient["status"] = "UNDER_REVIEW"
    touch(ingredient)
    return ok(ingredient)


@bp.post("/ingredients/<ingredient_id>/approve")
def approve_ingredient(ingredient_id):
    require_roles("CertificationReviewer")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    if ingredient["status"] != "UNDER_REVIEW":
        err("ERR_INGREDIENT_INVALID_STATE",
            "approve requires ingredient status UNDER_REVIEW")
    if (ingredient["source_category"] == "ANIMAL"
            and not ingredient["has_species_documentation"]):
        err("ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED",
            "Approving an ANIMAL ingredient requires species/slaughter documentation")
    ingredient["status"] = "APPROVED"
    touch(ingredient)
    # Re-approval compensation cascade (no-op on first approval).
    ingredient_compensation_cascade(ingredient)
    return ok(ingredient)


@bp.post("/ingredients/<ingredient_id>/reject")
def reject_ingredient(ingredient_id):
    require_roles("CertificationReviewer")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    if ingredient["status"] != "UNDER_REVIEW":
        err("ERR_INGREDIENT_INVALID_STATE",
            "reject requires ingredient status UNDER_REVIEW")
    ingredient["status"] = "REJECTED"
    touch(ingredient)
    for j in store.product_ingredients.values():
        if j["ingredient_id"] == ingredient_id and j["status"] == "PENDING_REAPPROVAL":
            j["status"] = "BLOCKED"
            touch(j)
    return ok(ingredient)


@bp.post("/ingredients/<ingredient_id>/change-notices")
def file_change_notice(ingredient_id):
    data = body_json()
    change_summary = req_str(data, "change_summary")
    require_roles("ClientContact")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    require_client_scope(ingredient["client_id"])
    if ingredient["status"] != "APPROVED":
        err("ERR_INGREDIENT_INVALID_STATE",
            "change notices require ingredient status APPROVED")
    ingredient["change_summary"] = change_summary
    ingredient["status"] = "CHANGE_PENDING"
    touch(ingredient)
    ingredient_freeze_cascade(ingredient)
    return created(ingredient)


@bp.post("/ingredients/<ingredient_id>/resubmit")
def resubmit_ingredient(ingredient_id):
    require_roles("ClientContact")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    require_client_scope(ingredient["client_id"])
    if ingredient["status"] != "CHANGE_PENDING":
        err("ERR_INGREDIENT_INVALID_STATE",
            "resubmit requires ingredient status CHANGE_PENDING")
    ingredient["status"] = "UNDER_REVIEW"
    touch(ingredient)
    return ok(ingredient)
