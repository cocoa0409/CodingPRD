"""Products, the shelf summary read, content revisions and attribute values."""
import re

from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (attribute_value_out, content_version_out, get_content_version, get_product,
                      product_out, require_attribute_key)
from errors import ApiError
from store import base_row, db, in_order, touch

bp = Blueprint("products", __name__)

GTIN_RE = re.compile(r"^\d{8,14}$")
PRODUCT_STATUSES = ("DRAFT", "ACTIVE")
GOVERNANCE_FLAGS = ("NONE", "CONTENT_AT_RISK", "LISTING_RISK")
VERSION_STATES = ("DRAFT", "IN_REVIEW", "PINNED", "SUPERSEDED")
LIFT_VARIANTS = ("post_pin_window", "quality_split")


# ------------------------------------------------------------------ products
@bp.route("/products", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_product():
    data = validate.body()
    sku = validate.req_str(data, "sku", 3, 40)
    gtin = validate.req_str(data, "gtin", 8, 14, GTIN_RE)
    category_code = validate.req_str(data, "category_code", 1)
    brand_code = validate.req_str(data, "brand_code", 1)
    for row in db.products.values():
        if row["sku"] == sku:
            validate.bad("sku")
    product = base_row()
    product.update({
        "sku": sku,
        "gtin": gtin,
        "category_code": category_code,
        "brand_code": brand_code,
        "status": "DRAFT",
        "shelf_health_index": calc.ZERO2,
        "conversion_lift_pct": calc.ZERO2,
        "open_alert_count": 0,
        "governance_flag": "NONE",
        "last_pinned_at": None,
        "last_review_at": None,
    })
    db.products[product["id"]] = product
    return envelope.created(product_out(product))


@bp.route("/products/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_product(row_id):
    return envelope.ok(product_out(get_product(row_id)))


@bp.route("/products", methods=["GET"])
@endpoint(ALL_ROLES)
def list_products():
    limit, offset = envelope.page_params()
    status = request.args.get("status")
    flag = request.args.get("governance_flag")
    rows = in_order(list(db.products.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if flag is not None:
        rows = [r for r in rows if r["governance_flag"] == flag]
    return envelope.paged_with(rows, product_out, limit, offset)


@bp.route("/products/<row_id>/shelf-summary", methods=["GET"])
@endpoint(ALL_ROLES)
def shelf_summary(row_id):
    variant = request.args.get("lift_variant")
    if variant is None:
        variant = "post_pin_window"
    if variant not in LIFT_VARIANTS:
        validate.bad("lift_variant")
    product = get_product(row_id)
    index, subscores = calc.shelf_health(product["id"])
    lift, high_size, base_size = calc.conversion_lift(product, variant)
    return envelope.ok({
        "product_id": product["id"],
        "shelf_health_index": index,
        "qualifying_listing_count": len(subscores),
        "retailer_subscores": subscores,
        "conversion_lift_pct": lift,
        "lift_variant": variant,
        "high_group_size": high_size,
        "base_group_size": base_size,
    })


# ---------------------------------------------------------- content versions
@bp.route("/content-versions", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_content_version():
    data = validate.body()
    product_id = validate.req_str(data, "product_id", 1)
    supersedes = validate.opt_str(data, "supersedes_content_version_id", 1)
    image_count = validate.opt_int(data, "image_count", 0, None, 0)
    product = get_product(product_id)
    if supersedes is not None:
        get_content_version(supersedes)
    revision_no = len(calc.versions_of_product(product["id"])) + 1
    version = base_row()
    version.update({
        "product_id": product["id"],
        "supersedes_content_version_id": supersedes,
        "revision_no": revision_no,
        "state": "DRAFT",
        "image_count": image_count,
        "pin_count": 0,
        "author_user_id": g.user_id,
    })
    db.content_versions[version["id"]] = version
    # The new revision becomes the DECLARED source the instant it exists.
    for listing in calc.listings_of_product(product["id"]):
        recompute.recompute_listing_declared(listing)
    return envelope.created(content_version_out(version))


@bp.route("/content-versions/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_content_version(row_id):
    return envelope.ok(content_version_out(get_content_version(row_id)))


@bp.route("/content-versions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_content_versions():
    limit, offset = envelope.page_params()
    product_id = request.args.get("product_id")
    supersedes = request.args.get("supersedes_content_version_id")
    state = request.args.get("state")
    rows = in_order(list(db.content_versions.values()))
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if supersedes is not None:
        rows = [r for r in rows if r.get("supersedes_content_version_id") == supersedes]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return envelope.paged_with(rows, content_version_out, limit, offset)


# --------------------------------------------------------- attribute values
@bp.route("/content-versions/<row_id>/attribute-values", methods=["POST"])
@endpoint(["ContentAuthor"])
def write_attribute_value(row_id):
    data = validate.body()
    attribute_key = validate.req_str(data, "attribute_key", 1, 40)
    value = validate.req_str(data, "value", 1, 2000)
    version = get_content_version(row_id)
    definition = require_attribute_key(attribute_key)
    if version["state"] != "DRAFT":
        raise ApiError("ERR_VERSION_NOT_DRAFT")
    stripped = value.strip()
    lowered = stripped.lower()
    for token in calc.PROHIBITED_CLAIM_TOKENS:
        if token in lowered:
            raise ApiError("ERR_PROHIBITED_CLAIM")
    char_count = len(stripped)
    if char_count > int(definition["max_chars"]):
        raise ApiError("ERR_ATTRIBUTE_LENGTH_EXCEEDED")

    existing = None
    for row in in_order(list(db.attribute_values.values())):
        if row["content_version_id"] == version["id"] and row["attribute_key"] == attribute_key:
            existing = row
            break
    if existing is None:
        row = base_row()
        row.update({
            "content_version_id": version["id"],
            "attribute_key": attribute_key,
            "value": value,
            "char_count": char_count,
            "type_valid": calc.type_valid(stripped, definition["data_type"]),
        })
        db.attribute_values[row["id"]] = row
    else:
        row = existing
        row["value"] = value
        row["char_count"] = char_count
        row["type_valid"] = calc.type_valid(stripped, definition["data_type"])
        touch(row)

    product = db.products.get(version["product_id"])
    recompute.recompute_product_listings_completeness(version["product_id"])
    if product is not None:
        recompute.recompute_product_health(product)
    return envelope.created(attribute_value_out(row))


@bp.route("/content-versions/<row_id>/attribute-values", methods=["GET"])
@endpoint(ALL_ROLES)
def list_attribute_values(row_id):
    limit, offset = envelope.page_params()
    version = get_content_version(row_id)
    rows = in_order([r for r in db.attribute_values.values()
                     if r["content_version_id"] == version["id"]])
    return envelope.paged_with(rows, attribute_value_out, limit, offset)
