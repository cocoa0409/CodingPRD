"""Product and ProductIngredient endpoints (PRD §3.4)."""
from flask import Blueprint

from db import new_common, store, touch
from errors import err
from middleware import get_or_404, require_client_scope, require_roles
from response import Paginator, created, ok
from services.domain import (product_junctions, recompute_certificate,
                             release_review_hold_if_clear)
from validation import body_json, req_str, req_str_list

bp = Blueprint("products", __name__)


def _create_junction(product_id, ingredient_id):
    junction = new_common({
        "product_id": product_id,
        "ingredient_id": ingredient_id,
        "status": "ACTIVE",
    })
    store.product_ingredients[junction["id"]] = junction
    return junction


@bp.post("/products")
def create_product():
    data = body_json()
    client_id = req_str(data, "client_id")
    brand = req_str(data, "brand")
    name = req_str(data, "name")
    ingredient_ids = req_str_list(data, "ingredient_ids")
    require_roles("ClientContact")
    require_client_scope(client_id)
    get_or_404(store.clients, client_id, "Client")
    ingredients = [get_or_404(store.ingredients, iid, "Ingredient")
                   for iid in ingredient_ids]
    for ing in ingredients:
        if ing["client_id"] != client_id:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "Ingredient %s belongs to a different client" % ing["id"])
    for ing in ingredients:
        if ing["status"] != "APPROVED":
            err("ERR_INGREDIENT_NOT_APPROVED",
                "Ingredient %s is not APPROVED" % ing["id"])
    if len(set(ingredient_ids)) != len(ingredient_ids):
        err("ERR_DUPLICATE_PRODUCT_INGREDIENT",
            "ingredient_ids contains a duplicate")
    product = new_common({
        "client_id": client_id,
        "brand": brand,
        "name": name,
        "status": "DRAFT",
    })
    store.products[product["id"]] = product
    for iid in ingredient_ids:
        _create_junction(product["id"], iid)
    return created(product)


@bp.get("/products")
def list_products():
    p = Paginator()
    rows = list(store.products.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "status")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/products/<product_id>")
def get_product(product_id):
    return ok(get_or_404(store.products, product_id, "Product"))


@bp.get("/products/<product_id>/ingredients")
def list_product_ingredients(product_id):
    get_or_404(store.products, product_id, "Product")
    p = Paginator()
    rows = product_junctions(product_id)
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/products/<product_id>/certificate-listings")
def list_product_certificate_listings(product_id):
    get_or_404(store.products, product_id, "Product")
    p = Paginator()
    rows = [e for e in store.certificate_products.values()
            if e["product_id"] == product_id]
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/products/<product_id>/ingredients")
def add_product_ingredient(product_id):
    data = body_json()
    ingredient_id = req_str(data, "ingredient_id")
    require_roles("ClientContact")
    product = get_or_404(store.products, product_id, "Product")
    require_client_scope(product["client_id"])
    if product["status"] == "WITHDRAWN":
        err("ERR_PRODUCT_INVALID_STATE",
            "WITHDRAWN is terminal; no ingredient may be added")
    ingredient = get_or_404(store.ingredients, ingredient_id, "Ingredient")
    if ingredient["client_id"] != product["client_id"]:
        err("ERR_CROSS_CLIENT_REFERENCE",
            "Ingredient %s belongs to a different client" % ingredient_id)
    if ingredient["status"] != "APPROVED":
        err("ERR_INGREDIENT_NOT_APPROVED",
            "Ingredient %s is not APPROVED" % ingredient_id)
    if any(j for j in product_junctions(product_id)
           if j["ingredient_id"] == ingredient_id and j["status"] != "REMOVED"):
        err("ERR_DUPLICATE_PRODUCT_INGREDIENT",
            "The ingredient already has a non-REMOVED junction on this product")
    return created(_create_junction(product_id, ingredient_id), )


@bp.delete("/product-ingredients/<junction_id>")
def remove_product_ingredient(junction_id):
    require_roles("ClientContact")
    junction = get_or_404(store.product_ingredients, junction_id, "ProductIngredient")
    product = store.products.get(junction["product_id"])
    if product is not None:
        require_client_scope(product["client_id"])
    if junction["status"] == "REMOVED":
        err("ERR_PRODUCT_INGREDIENT_INVALID_STATE",
            "Junction is already REMOVED")
    if product is not None and product["status"] == "WITHDRAWN":
        err("ERR_PRODUCT_INVALID_STATE",
            "Junction removal is not allowed on a WITHDRAWN product")
    junction["status"] = "REMOVED"
    touch(junction)
    # REVIEW_HOLD release valve (PRD §3.4).
    if product is not None:
        release_review_hold_if_clear(product)
    return ok(junction)


@bp.post("/products/<product_id>/submit-review")
def submit_product_review(product_id):
    require_roles("ClientContact")
    product = get_or_404(store.products, product_id, "Product")
    require_client_scope(product["client_id"])
    if product["status"] != "DRAFT":
        err("ERR_PRODUCT_INVALID_STATE",
            "submit-review requires product status DRAFT")
    if not any(j["status"] == "ACTIVE" for j in product_junctions(product_id)):
        err("ERR_PRODUCT_HAS_NO_INGREDIENTS",
            "submit-review requires at least one ACTIVE ingredient junction")
    product["status"] = "IN_REVIEW"
    touch(product)
    return ok(product)


@bp.post("/products/<product_id>/certify-eligible")
def certify_eligible(product_id):
    require_roles("CertificationReviewer")
    product = get_or_404(store.products, product_id, "Product")
    if product["status"] != "IN_REVIEW":
        err("ERR_PRODUCT_INVALID_STATE",
            "certify-eligible requires product status IN_REVIEW")
    for j in product_junctions(product_id):
        if j["status"] != "ACTIVE":
            continue
        ingredient = store.ingredients.get(j["ingredient_id"])
        if ingredient is None or ingredient["status"] != "APPROVED":
            err("ERR_INGREDIENT_NOT_APPROVED",
                "Every ACTIVE junction must link an APPROVED ingredient")
    product["status"] = "CERTIFIABLE"
    touch(product)
    return ok(product)


@bp.post("/products/<product_id>/withdraw")
def withdraw_product(product_id):
    require_roles("ClientContact")
    product = get_or_404(store.products, product_id, "Product")
    require_client_scope(product["client_id"])
    if product["status"] not in ("DRAFT", "IN_REVIEW", "CERTIFIABLE", "REVIEW_HOLD"):
        err("ERR_PRODUCT_INVALID_STATE",
            "withdraw requires product status DRAFT, IN_REVIEW, CERTIFIABLE or REVIEW_HOLD")
    product["status"] = "WITHDRAWN"
    touch(product)
    affected_certs = set()
    for e in store.certificate_products.values():
        if e["product_id"] == product_id and e["status"] in ("INCLUDED", "FROZEN"):
            e["status"] = "REMOVED"
            touch(e)
            affected_certs.add(e["certificate_id"])
    for cid in affected_certs:
        recompute_certificate(store.certificates[cid])
    return ok(product)
