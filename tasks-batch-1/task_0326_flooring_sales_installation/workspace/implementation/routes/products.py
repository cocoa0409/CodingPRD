"""Catalog Product endpoints."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok, ok_list
from services import serialize
from services.helpers import (
    CATEGORIES,
    body,
    is_int,
    pagination,
    paginate,
    require_fields,
    require_int_min,
    sort_by_created,
)

bp = Blueprint("products", __name__)

LIVE_JOB_STATUSES = {"DRAFT", "MEASURED", "RE_MEASURE", "ESTIMATED", "ACCEPTED", "IN_INSTALL"}


@bp.post("/flooring/products")
@require_roles("Admin")
def create_product():
    data = body()
    require_fields(
        data,
        ["sku", "name", "category", "material_cost_per_sqft_cents", "labor_rate_per_sqft_cents", "warranty_years"],
    )
    sku = data["sku"]
    name = data["name"]
    category = data["category"]
    if not isinstance(sku, str) or not isinstance(name, str):
        raise err("ERR_INVALID_REQUEST", "sku and name must be strings.")
    if category not in CATEGORIES:
        raise err("ERR_INVALID_REQUEST", "category must be one of HARDWOOD, LVP, TILE, CARPET.")

    material_cost = require_int_min(data, "material_cost_per_sqft_cents", 1)
    labor_rate = require_int_min(data, "labor_rate_per_sqft_cents", 1)
    warranty_years = require_int_min(data, "warranty_years", 0)

    requires_underlayment = data.get("requires_underlayment", False)
    if not isinstance(requires_underlayment, bool):
        raise err("ERR_INVALID_REQUEST", "requires_underlayment must be a boolean.")

    underlayment_cost = data.get("underlayment_cost_per_sqft_cents", 0)
    if not is_int(underlayment_cost) or underlayment_cost < 0:
        raise err("ERR_INVALID_REQUEST", "underlayment_cost_per_sqft_cents must be an integer >= 0.")

    lead_time_days = data.get("lead_time_days", 0)
    if not is_int(lead_time_days) or lead_time_days < 0:
        raise err("ERR_INVALID_REQUEST", "lead_time_days must be an integer >= 0.")

    # Underlayment consistency.
    if requires_underlayment:
        if underlayment_cost < 1:
            raise err(
                "ERR_INVALID_REQUEST",
                "underlayment_cost_per_sqft_cents must be >= 1 when requires_underlayment is true.",
            )
    else:
        if underlayment_cost != 0:
            raise err(
                "ERR_INVALID_REQUEST",
                "underlayment_cost_per_sqft_cents must be 0 when requires_underlayment is false.",
            )

    with db.lock:
        # sku unique among ACTIVE products, case-sensitive.
        for p in db.products.values():
            if p["status"] == "ACTIVE" and p["sku"] == sku:
                raise err("ERR_DUPLICATE_KEY", "A product with this SKU already exists.")
        record = stamp_create(
            {
                "sku": sku,
                "name": name,
                "category": category,
                "material_cost_per_sqft_cents": material_cost,
                "labor_rate_per_sqft_cents": labor_rate,
                "requires_underlayment": requires_underlayment,
                "underlayment_cost_per_sqft_cents": underlayment_cost,
                "lead_time_days": lead_time_days,
                "warranty_years": warranty_years,
                "status": "ACTIVE",
            }
        )
        db.products[record["id"]] = record
    return created(serialize.product_view(record))


@bp.get("/flooring/products/<pid>")
@require_roles("Admin", "SalesRep", "Estimator", "Scheduler", "Customer")
def get_product(pid):
    with db.lock:
        p = db.products.get(pid)
        if p is None:
            raise err("ERR_NOT_FOUND", "Product not found.")
        return ok(serialize.product_view(p))


@bp.get("/flooring/products")
@require_roles("Admin", "SalesRep", "Estimator", "Scheduler", "Customer")
def list_products():
    limit, offset = pagination()
    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None and category not in CATEGORIES:
        raise err("ERR_INVALID_REQUEST", "Invalid category filter.")
    with db.lock:
        items = list(db.products.values())
        if category is not None:
            items = [p for p in items if p["category"] == category]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.product_view(p) for p in page]
    return ok_list(views, limit, offset, total)


@bp.post("/flooring/products/<pid>/discontinue")
@require_roles("Admin")
def discontinue_product(pid):
    with db.lock:
        p = db.products.get(pid)
        if p is None:
            raise err("ERR_NOT_FOUND", "Product not found.")
        if p["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Only an ACTIVE product can be discontinued.")
        # Blocked while any referencing job is live.
        for j in db.jobs.values():
            if j["product_id"] == pid and j["status"] in LIVE_JOB_STATUSES:
                raise err(
                    "ERR_INVALID_STATE",
                    "Cannot discontinue: a live job references this product.",
                )
        p["status"] = "DISCONTINUED"
        touch(p)
        return ok(serialize.product_view(p))
