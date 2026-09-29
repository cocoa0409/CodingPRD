"""Supplier registration, standing changes and read."""

from flask import Blueprint

import db
import middleware as mw
import query
import response
from constants import (
    READ_SUPPLIERS,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_PROGRAM_ADMIN,
    SUPPLIER_STATUSES,
)
from errors import ApiError
from services import derive

bp = Blueprint("suppliers", __name__)


@bp.post("/gfco/suppliers")
def create_supplier():
    mw.authenticate([ROLE_PROGRAM_ADMIN, ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    name = mw.req_str(data, "name")
    country_code = mw.req_country(data, "country_code")
    disclosed = mw.opt_bool(data, "gluten_handling_disclosed", False)
    row = db.insert(
        db.suppliers,
        {
            "name": name,
            "country_code": country_code,
            "gluten_handling_disclosed": disclosed,
            "status": "ACTIVE",
            "verified_document_count": 0,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/suppliers/<supplier_id>")
def get_supplier(supplier_id):
    mw.authenticate(READ_SUPPLIERS)
    return response.ok(response.serialize(query.fetch("supplier", supplier_id)))


@bp.post("/gfco/suppliers/<supplier_id>/status")
def change_supplier_status(supplier_id):
    mw.authenticate([ROLE_PROGRAM_ADMIN])
    data = mw.body()
    new_status = mw.req_enum(data, "status", SUPPLIER_STATUSES)
    supplier = query.fetch("supplier", supplier_id)
    if supplier["status"] == new_status:
        raise ApiError("ERR_SUPPLIER_STATUS_UNCHANGED")

    previous = supplier["status"]
    supplier["status"] = new_status
    db.touch(supplier)

    if new_status == "SUSPENDED":
        _suspension_cascade(supplier)
    elif new_status == "ACTIVE" and previous == "SUSPENDED":
        _reinstatement_cascade(supplier)

    return response.ok(response.serialize(supplier))


def _suspension_cascade(supplier):
    """Five hops: ingredients, compound parents, formulas, marks, labels."""
    direct = [
        ingredient
        for ingredient in db.ordered(db.ingredients)
        if ingredient["supplier_id"] == supplier["id"]
        and ingredient["status"] == "APPROVED"
    ]
    blocked = []
    for ingredient in direct:
        blocked.extend(
            derive.block_ingredient_chain(ingredient, "SUPPLIER_SUSPENDED")
        )
    if blocked:
        derive.refresh_products_of_ingredients([i["id"] for i in blocked])


def _reinstatement_cascade(supplier):
    """Only supplier-suspension blocks are released, and only back to review."""
    released = []
    for ingredient in db.ordered(db.ingredients):
        if (
            ingredient["supplier_id"] == supplier["id"]
            and ingredient["status"] == "BLOCKED"
            and ingredient["blocked_reason"] == "SUPPLIER_SUSPENDED"
        ):
            ingredient["status"] = "UNDER_REVIEW"
            ingredient["blocked_reason"] = None
            ingredient["review_cycle_count"] = ingredient["review_cycle_count"] + 1
            db.touch(ingredient)
            released.append(ingredient)
    if released:
        product_ids = {
            link["product_id"]
            for link in db.product_ingredients.values()
            if link["ingredient_id"] in {i["id"] for i in released}
        }
        for product_id in product_ids:
            product = db.products.get(product_id)
            if product is None:
                continue
            before = db.snapshot(product)
            derive.recompute_product_counts(product)
            db.touch_if_changed(product, before)
