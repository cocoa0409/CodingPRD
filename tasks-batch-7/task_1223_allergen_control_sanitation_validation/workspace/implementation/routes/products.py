from flask import Blueprint

from db import db, new_entity, public, touch
from errors import ApiError
from logic import create_auto_incident, get_or_404
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import (body, opt_bool, opt_int, opt_list_str, query_bool, req_enum,
                  req_list_str, req_str)

bp = Blueprint("products", __name__)

REWORK_CLASSES = ("SAME_INTO_SAME", "SAME_ALLERGEN_PROFILE",
                  "RESTRICTED_REWORK", "NO_REWORK")


def _check_allergen_set_active(allergen_set):
    code_map = {a["code"]: a for a in db["allergens"].values()}
    for code in allergen_set:
        al = code_map.get(code)
        if al is None or not al["is_active"]:
            raise ApiError("ERR_ALLERGEN_INACTIVE", 422,
                           f"Allergen code does not resolve to an active allergen: {code}")


@bp.post("/qa/products")
@require_roles("QaManager")
def create_product():
    b = body()
    sku = req_str(b, "sku")
    if any(p["sku"] == sku for p in db["products"].values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Duplicate sku: {sku}")
    product_name = req_str(b, "product_name")
    allergen_set = req_list_str(b, "allergen_set")
    rework_class = req_enum(b, "rework_class", REWORK_CLASSES)
    label_revision = opt_int(b, "label_revision", 1, minv=1)
    is_active = opt_bool(b, "is_active", True)
    _check_allergen_set_active(allergen_set)
    ent = new_entity({
        "sku": sku,
        "product_name": product_name,
        "allergen_set": allergen_set,
        "rework_class": rework_class,
        "label_revision": label_revision,
        "is_active": is_active,
    })
    db["products"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/products")
@require_roles(*ALL_ROLES)
def list_products():
    active = query_bool("is_active")
    items = list(db["products"].values())
    if active is not None:
        items = [p for p in items if p["is_active"] == active]
    return ok_list(items)


@bp.get("/qa/products/<productId>")
@require_roles(*ALL_ROLES)
def get_product(productId):
    return ok(public(get_or_404("products", productId)))


@bp.patch("/qa/products/<productId>")
@require_roles("QaManager")
def patch_product(productId):
    product = get_or_404("products", productId)
    b = body()
    changed = False
    if "label_revision" in b:
        product["label_revision"] = opt_int(b, "label_revision", None, minv=1)
        changed = True
    if "is_active" in b:
        product["is_active"] = opt_bool(b, "is_active", None)
        changed = True
    if "allergen_set" in b:
        new_set = opt_list_str(b, "allergen_set")
        if set(new_set) != set(product["allergen_set"]):
            product["allergen_set"] = new_set
            create_auto_incident(
                "SUPPLIER_ALLERGEN_CHANGE", "MEDIUM",
                product_id=product["id"],
                description=f"Allergen set changed for product {product['sku']}")
        changed = True
    if changed:
        touch(product)
    return ok(public(product))


@bp.post("/qa/products/<productId>/supplier-allergen-change")
@require_roles("QaManager")
def supplier_allergen_change(productId):
    product = get_or_404("products", productId)
    b = body()
    new_set = req_list_str(b, "new_allergen_set")
    notice_ref = req_str(b, "supplier_notice_ref")
    product["allergen_set"] = new_set
    product["label_revision"] += 1
    touch(product)
    create_auto_incident(
        "SUPPLIER_ALLERGEN_CHANGE", "MEDIUM",
        product_id=product["id"],
        description=f"Supplier allergen change (notice {notice_ref}) for product {product['sku']}")
    return ok(public(product))
