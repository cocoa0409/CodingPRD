"""Product and Variant endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.serialize import serialize

bp = Blueprint("products", __name__)

VALID_CATEGORIES = {"APPAREL", "DRINKWARE", "ACCESSORY", "PRINT"}


def _get_product_or_404(pid):
    row = db.products.get(pid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"product {pid} not found")
    return row


def _get_variant_or_404(vid):
    row = db.variants.get(vid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"variant {vid} not found")
    return row


@bp.post("/pod/products")
@require_auth(["PlatformAdmin"])
def create_product():
    body = request.get_json(silent=True) or {}
    for f in ("sku", "category", "base_cost_cents", "dimensions_json"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    cat = body["category"]
    if cat not in VALID_CATEGORIES:
        raise_error("ERR_INVALID_REQUEST", "unknown category")
    base_cost = body["base_cost_cents"]
    if not isinstance(base_cost, int) or isinstance(base_cost, bool) or base_cost < 100:
        raise_error("ERR_INVALID_REQUEST", "base_cost_cents must be int >= 100")
    if not isinstance(body["dimensions_json"], dict):
        raise_error("ERR_INVALID_REQUEST", "dimensions_json must be an object")
    sku = body["sku"]
    if not isinstance(sku, str) or not sku:
        raise_error("ERR_INVALID_REQUEST", "sku must be non-empty string")
    for p in db.products.all():
        if p["sku"] == sku:
            raise_error("ERR_INVALID_REQUEST", "sku already exists")

    row = db.new_common_fields()
    row.update(
        {
            "sku": sku,
            "category": cat,
            "base_cost_cents": base_cost,
            "dimensions_json": body["dimensions_json"],
        }
    )
    db.products.insert(row)
    return created(serialize(row))


@bp.get("/pod/products/<pid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_product(pid):
    return ok(serialize(_get_product_or_404(pid)))


@bp.post("/pod/products/<pid>/variants")
@require_auth(["PlatformAdmin"])
def create_variant(pid):
    product = _get_product_or_404(pid)
    body = request.get_json(silent=True) or {}
    for f in ("color", "size"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    delta = body.get("base_cost_delta_cents", 0)
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise_error("ERR_INVALID_REQUEST", "base_cost_delta_cents must be int")

    row = db.new_common_fields()
    row.update(
        {
            "product_id": product["id"],
            "color": body["color"],
            "size": body["size"],
            "base_cost_delta_cents": delta,
            "active": True,
        }
    )
    db.variants.insert(row)
    return created(serialize(row))


@bp.get("/pod/variants/<vid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_variant(vid):
    return ok(serialize(_get_variant_or_404(vid)))


@bp.get("/pod/variants")
@require_auth(["Creator", "PlatformAdmin"])
def list_variants():
    product_id = request.args.get("product_id")
    rows = db.variants.all()
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)
