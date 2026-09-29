"""Formula lines: the immutable product-to-ingredient junction."""

from flask import Blueprint

import db
import middleware as mw
import query
import response
from constants import READ_PRODUCT_INGREDIENTS, ROLE_APPLICANT_CONTACT
from errors import ApiError
from services import derive

bp = Blueprint("product_ingredients", __name__)


@bp.post("/gfco/product-ingredients")
def create_line():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    product_id = mw.req_str(data, "product_id")
    ingredient_id = mw.req_str(data, "ingredient_id")
    inclusion_pct = mw.req_num(
        data, "inclusion_pct", exclusive_min=0, maximum=100
    )

    product = query.fetch("product", product_id)
    ingredient = query.fetch("ingredient", ingredient_id)

    if product["applicant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if ingredient["status"] == "REJECTED":
        raise ApiError("ERR_INVALID_INGREDIENT_STATE")
    if product["formula_status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_PRODUCT_STATE")
    supplier = db.suppliers.get(ingredient["supplier_id"])
    if supplier is not None and supplier["status"] == "SUSPENDED":
        raise ApiError("ERR_SUPPLIER_SUSPENDED")
    for link in db.product_ingredients.values():
        if link["product_id"] == product_id \
                and link["ingredient_id"] == ingredient_id:
            raise ApiError("ERR_DUPLICATE_PRODUCT_INGREDIENT")

    row = db.insert(
        db.product_ingredients,
        {
            "product_id": product_id,
            "ingredient_id": ingredient_id,
            "inclusion_pct": inclusion_pct,
            "is_risk_carrier": ingredient["risk_class"] != "INHERENTLY_GF",
        },
        versioned=False,
    )
    before = db.snapshot(product)
    derive.recompute_product_counts(product)
    db.touch_if_changed(product, before)
    return response.created(response.serialize(row))


@bp.get("/gfco/product-ingredients/<link_id>")
def get_line(link_id):
    mw.authenticate(READ_PRODUCT_INGREDIENTS)
    return response.ok(
        response.serialize(query.fetch("product_ingredient", link_id))
    )


@bp.get("/gfco/product-ingredients")
def list_lines():
    mw.authenticate(READ_PRODUCT_INGREDIENTS)
    return query.listing(
        db.product_ingredients,
        {
            "product_id": query.arg("product_id"),
            "ingredient_id": query.arg("ingredient_id"),
        },
    )
