"""Products (PRD §3.1): SKU master, spec edits, discontinue, reformulation."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PRODUCT_VERSION_PINNED,
    ERR_STALE_VERSION,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize
from util import (
    apply_filters,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = Blueprint("products", __name__)

FORMATS = {"NOVELTY", "BULK"}
FLAVOR_FAMILIES = {"VANILLA", "CHOCOLATE", "FRUIT", "CARAMEL", "NUT_BAKERY", "COFFEE"}
ALLERGENS = {"MILK", "EGG", "SOY", "WHEAT", "PEANUT", "TREE_NUT", "SESAME"}

PRODUCT_SPEC = {
    "sku_code": {"type": "string", "required": True},
    "product_name": {"type": "string", "required": True},
    "format": {"type": "enum", "values": FORMATS, "required": True},
    "flavor_family": {"type": "enum", "values": FLAVOR_FAMILIES, "required": True},
    "allergens": {"type": "str_list", "values": ALLERGENS, "required": True},
    "fill_volume_ml_per_unit": {
        "type": "number", "min": 0, "min_exclusive": True, "required": True,
    },
    "target_overrun_pct": {"type": "number", "min": 0, "max": 100, "required": True},
    "units_per_pallet": {"type": "integer", "min": 1, "required": True},
    "shelf_life_days": {"type": "integer", "min": 1, "required": True},
    "co_pack_only": {"type": "boolean"},
}

PATCH_SPEC = {
    "product_name": {"type": "string"},
    "flavor_family": {"type": "enum", "values": FLAVOR_FAMILIES},
    "allergens": {"type": "str_list", "values": ALLERGENS},
    "fill_volume_ml_per_unit": {"type": "number", "min": 0, "min_exclusive": True},
    "target_overrun_pct": {"type": "number", "min": 0, "max": 100},
    "units_per_pallet": {"type": "integer", "min": 1},
    "shelf_life_days": {"type": "integer", "min": 1},
    "co_pack_only": {"type": "boolean"},
}


def _new_product_fields(body):
    return {
        "sku_code": body["sku_code"],
        "product_name": body["product_name"],
        "format": body["format"],
        "flavor_family": body["flavor_family"],
        "allergens": list(body["allergens"]),
        "fill_volume_ml_per_unit": body["fill_volume_ml_per_unit"],
        "target_overrun_pct": body["target_overrun_pct"],
        "units_per_pallet": body["units_per_pallet"],
        "shelf_life_days": body["shelf_life_days"],
        "co_pack_only": body.get("co_pack_only", False),
        "status": "ACTIVE",
        "predecessor_product_id": None,
        "successor_product_id": None,
    }


@bp.route("/products", methods=["POST"])
def create_product():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, PRODUCT_SPEC)
    product = db.new_entity("products", _new_product_fields(body))
    return success_obj(serialize("products", product), 201)


@bp.route("/products", methods=["GET"])
def list_products():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("products"),
        ["format", "status", "flavor_family", "predecessor_product_id",
         "successor_product_id"],
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("products", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    authenticate(ALL_ROLES)
    product = path_entity("products", product_id, "product")
    return success_obj(serialize("products", product))


@bp.route("/products/<product_id>", methods=["PATCH"])
def patch_product(product_id):
    authenticate({"PlantManager"})
    product = path_entity("products", product_id, "product")
    body = body_json()
    check_shape(body, PATCH_SPEC)
    # Priority 36: spec edits are forbidden while an APPROVED/ACTIVE contract
    # has pinned this product's version.
    for contract in db.all_of("contracts"):
        if (
            contract["product_id"] == product_id
            and contract["status"] in ("APPROVED", "ACTIVE")
            and contract.get("pinned_product_version") is not None
        ):
            raise ApiError(
                ERR_PRODUCT_VERSION_PINNED,
                409,
                "product spec is pinned by an APPROVED or ACTIVE co-pack contract",
            )
    for field in PATCH_SPEC:
        if field in body and body[field] is not None:
            product[field] = list(body[field]) if field == "allergens" else body[field]
    db.touch(product)
    return success_obj(serialize("products", product))


@bp.route("/products/<product_id>/discontinue", methods=["POST"])
def discontinue_product(product_id):
    authenticate({"PlantManager"})
    product = path_entity("products", product_id, "product")
    if product["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "product is not ACTIVE")
    product["status"] = "DISCONTINUED"
    db.touch(product)
    return success_obj(serialize("products", product))


@bp.route("/products/<product_id>/reformulations", methods=["POST"])
def create_reformulation(product_id):
    authenticate({"PlantManager"})
    parent = path_entity("products", product_id, "product")
    body = body_json()
    spec = dict(PRODUCT_SPEC)
    spec["expected_product_version"] = {"type": "integer", "required": True}
    check_shape(body, spec)
    # OCC (PRD §2.6): stale writers must re-read before retrying.
    if body["expected_product_version"] != parent["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_product_version does not match the product's current version",
        )
    child = db.new_entity("products", _new_product_fields(body))
    child["predecessor_product_id"] = parent["id"]
    parent["successor_product_id"] = child["id"]
    db.touch(parent)
    return success_obj(serialize("products", child), 201)
