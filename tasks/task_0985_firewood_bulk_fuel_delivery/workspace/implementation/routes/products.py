"""Product endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_product
from util import (
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    require_number,
    require_str,
    touch,
)

bp = Blueprint("products", __name__)

PRODUCT_KINDS = {"CORD", "HALF_CORD", "PELLET_TON", "PELLET_BAG"}
SPECIES_ALL = {"OAK", "MAPLE", "BIRCH", "MIXED_HARDWOOD", "HARDWOOD_BLEND", "SOFTWOOD_BLEND"}
PELLET_SPECIES = {"HARDWOOD_BLEND", "SOFTWOOD_BLEND"}
GRADES = {"GREEN", "SEMI_SEASONED", "KILN_DRIED"}


def _validate_product_spec(product_kind, species, seasoned_grade):
    if seasoned_grade not in GRADES:
        raise errors.invalid_product_spec(f"Invalid seasoned_grade: {seasoned_grade}")
    if product_kind in ("PELLET_TON", "PELLET_BAG") and species not in PELLET_SPECIES:
        raise errors.invalid_product_spec("Pellet kinds require a pellet-blend species")
    if species not in SPECIES_ALL:
        raise errors.invalid_product_spec(f"Invalid species: {species}")


@bp.post("/api/v1/products")
def create_product():
    require_roles("OperationsManager")
    body = get_json_body()
    sku = require_str(body, "sku")
    product_kind = require_str(body, "product_kind")
    if product_kind not in PRODUCT_KINDS:
        raise errors.invalid_product_spec(f"Invalid product_kind: {product_kind}")
    species = require_str(body, "species")
    seasoned_grade = require_str(body, "seasoned_grade")
    _validate_product_spec(product_kind, species, seasoned_grade)
    base_price_cents = require_int(body, "base_price_cents")
    moisture_ceiling_pct = require_number(body, "moisture_ceiling_pct")
    available_qty = require_number(body, "available_qty")
    discontinued = body.get("discontinued", False)
    if not isinstance(discontinued, bool):
        raise errors.validation("discontinued must be a boolean")
    ts = now_iso()
    pid = new_id()
    product = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "sku": sku,
        "product_kind": product_kind,
        "species": species,
        "seasoned_grade": seasoned_grade,
        "base_price_cents": base_price_cents,
        "moisture_ceiling_pct": moisture_ceiling_pct,
        "available_qty": available_qty,
        "reserved_qty": 0,
        "discontinued": discontinued,
    }
    db.products[pid] = product
    return success_object(serialize_product(product), status=201)


def _get_product_or_404(pid):
    p = db.products.get(pid)
    if not p:
        raise errors.not_found(f"Product {pid} not found")
    return p


@bp.get("/api/v1/products/<pid>")
def get_product(pid):
    require_roles("CustomerService", "OperationsManager", "Customer", "Driver", "RoutePlanner")
    return success_object(serialize_product(_get_product_or_404(pid)))


@bp.get("/api/v1/products")
def list_products():
    require_roles("CustomerService", "OperationsManager", "Customer", "Driver", "RoutePlanner")
    limit, offset = parse_pagination()
    items = list(db.products.values())
    for f in ("product_kind", "seasoned_grade", "species"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    d = request.args.get("discontinued")
    if d is not None:
        dval = d.lower() in ("true", "1", "yes")
        items = [p for p in items if p.get("discontinued", False) == dval]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_product(p) for p in page], total, limit, offset)


@bp.patch("/api/v1/products/<pid>")
def update_product(pid):
    require_roles("OperationsManager")
    product = _get_product_or_404(pid)
    body = get_json_body()
    if "base_price_cents" in body:
        v = body["base_price_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise errors.validation("base_price_cents must be an integer")
        product["base_price_cents"] = v
    if "moisture_ceiling_pct" in body:
        v = body["moisture_ceiling_pct"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise errors.validation("moisture_ceiling_pct must be a number")
        product["moisture_ceiling_pct"] = v
    if "available_qty" in body:
        v = body["available_qty"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise errors.validation("available_qty must be a number")
        product["available_qty"] = v
    if "discontinued" in body:
        v = body["discontinued"]
        if not isinstance(v, bool):
            raise errors.validation("discontinued must be a boolean")
        product["discontinued"] = v
    # Seasoned grade / species updates validated if provided
    if "seasoned_grade" in body or "species" in body:
        grade = body.get("seasoned_grade", product["seasoned_grade"])
        species = body.get("species", product["species"])
        _validate_product_spec(product["product_kind"], species, grade)
        product["seasoned_grade"] = grade
        product["species"] = species
    touch(product)
    return success_object(serialize_product(product))
