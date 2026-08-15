"""Product catalog endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE_SKU, ERR_PRODUCT_INVALID_STATE
from middleware import authorized
from response import success_object, success_list
from services.calculations import PRODUCT_TYPES
from services.core import (
    get_body, require_fields, require_string, require_int, require_enum,
    public, get_or_404, paginate,
)
from util import new_id, now_ts, touch

bp = Blueprint("products", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "SupplyChainPlanner", "ComplianceOfficer"]


@bp.route("/vet/products", methods=["POST"])
def create_product():
    authorized(["SupplyChainPlanner"])
    body = get_body()
    require_fields(body, ["sku", "product_name", "manufacturer_code",
                          "product_type", "unit_price_cents"])
    sku = require_string(body, "sku")
    product_name = require_string(body, "product_name")
    manufacturer_code = require_string(body, "manufacturer_code")
    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    is_controlled = body.get("is_controlled_substance", False)
    if not isinstance(is_controlled, bool):
        raise_error(("ERR_INVALID_REQUEST", 400),
                    "is_controlled_substance must be a boolean")
    unit_price = require_int(body, "unit_price_cents", minimum=1)

    # SKU uniqueness across all products
    for p in db["products"].values():
        if p["sku"] == sku:
            raise_error(ERR_DUPLICATE_SKU, f"sku already exists: {sku}")

    product = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "sku": sku,
        "product_name": product_name,
        "manufacturer_code": manufacturer_code,
        "product_type": product_type,
        "is_controlled_substance": is_controlled,
        # requires_cold_chain is computed: true iff VACCINE; input ignored (PRD 2.10)
        "requires_cold_chain": product_type == "VACCINE",
        "unit_price_cents": unit_price,
        "status": "LISTED",
    }
    db["products"][product["id"]] = product
    return success_object(public(product), status=201)


@bp.route("/vet/products", methods=["GET"])
def list_products():
    authorized(READ_ROLES)
    items = list(db["products"].values())
    for param in ("sku", "manufacturer_code", "product_type", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if str(p.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([public(p) for p in page], total, limit, offset)


@bp.route("/vet/products/<pid>", methods=["GET"])
def get_product(pid):
    authorized(READ_ROLES)
    product = get_or_404("products", pid)
    return success_object(public(product))


@bp.route("/vet/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    authorized(["SupplyChainPlanner"])
    product = get_or_404("products", pid)
    if product["status"] != "LISTED":
        raise_error(ERR_PRODUCT_INVALID_STATE,
                    f"product must be LISTED (is {product['status']})")
    product["status"] = "DISCONTINUED"
    touch(product)
    return success_object(public(product))
