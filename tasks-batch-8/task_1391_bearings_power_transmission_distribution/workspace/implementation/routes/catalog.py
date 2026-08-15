"""Products, interchange records, price files."""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (FAMILIES, get_body, new_id, req_dt, req_enum, req_int,
                     req_num, req_str, stamp_new, touch, now)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list

bp = Blueprint("catalog", __name__)


def get_product(pid):
    p = store.products.get(pid)
    if p is None:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {pid} not found")
    return p


# --------------------------------------------------------------- products --

@bp.route("/motion/products", methods=["POST"])
@require_roles("PricingAnalyst")
def create_product(user_id, role):
    body = get_body()
    sku = req_str(body, "sku")
    description = req_str(body, "description")
    family = req_enum(body, "family", FAMILIES)
    list_price = req_int(body, "list_price_cents", minimum=0)
    if any(p["sku"] == sku for p in store.products.values()):
        raise err("ERR_DUPLICATE_SKU", f"sku {sku} already exists")
    rec = stamp_new({
        "id": new_id(),
        "sku": sku,
        "description": description,
        "family": family,
        "list_price_cents": list_price,
        "_original_list_price_cents": list_price,
        "last_price_change_at": None,
        "superseded_by_id": body.get("superseded_by_id"),
        "status": "ACTIVE",
    })
    store.products[rec["id"]] = rec
    return ok(serialize("Product", rec), 201)


@bp.route("/motion/products", methods=["GET"])
@require_any
def list_products(user_id, role):
    items = list(store.products.values())
    q = request.args
    if q.get("sku") is not None:
        items = [p for p in items if p["sku"] == q["sku"]]
    if q.get("family") is not None:
        items = [p for p in items if p["family"] == q["family"]]
    if q.get("status") is not None:
        items = [p for p in items if p["status"] == q["status"]]
    if q.get("superseded_by_id") is not None:
        items = [p for p in items if p["superseded_by_id"] == q["superseded_by_id"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("Product", page), limit, offset, total)


@bp.route("/motion/products/<pid>", methods=["GET"])
@require_any
def get_product_route(user_id, role, pid):
    return ok(serialize("Product", get_product(pid)))


@bp.route("/motion/products/<pid>", methods=["PATCH"])
@require_roles("PricingAnalyst")
def patch_product(user_id, role, pid):
    p = get_product(pid)
    body = get_body()
    target = req_enum(body, "status", ("ACTIVE", "PHASEOUT", "OBSOLETE"))
    sup = body.get("superseded_by_id")

    # state (priority 5)
    if target == "ACTIVE":
        if p["status"] != "ACTIVE":
            raise err("ERR_PRODUCT_NOT_ACTIVE", "product is not ACTIVE")
        # ACTIVE -> ACTIVE: no transition defined; treat as invalid request
        raise err("ERR_INVALID_REQUEST", "no lifecycle transition to ACTIVE")
    if target == "PHASEOUT":
        if p["status"] != "ACTIVE":
            raise err("ERR_PRODUCT_NOT_ACTIVE", "PHASEOUT requires current status ACTIVE")
    if target == "OBSOLETE":
        if p["status"] == "OBSOLETE":
            raise err("ERR_PRODUCT_NOT_PHASEOUT", "product already OBSOLETE")
        if p["status"] not in ("ACTIVE", "PHASEOUT"):
            raise err("ERR_PRODUCT_NOT_PHASEOUT", "OBSOLETE requires ACTIVE or PHASEOUT")
        # referential (priority 9): supersede target must exist and be ACTIVE
        if sup is not None:
            tgt = store.products.get(sup)
            if tgt is None or tgt["status"] != "ACTIVE":
                raise err("ERR_SUPERSEDE_TARGET_INVALID",
                          "superseded_by_id must reference an existing ACTIVE product")

    p["status"] = target
    if target == "OBSOLETE" and sup is not None:
        p["superseded_by_id"] = sup
    touch(p)
    return ok(serialize("Product", p))


# ---------------------------------------------------------- interchanges ---

@bp.route("/motion/interchange-records", methods=["POST"])
@require_roles("PricingAnalyst")
def create_interchange(user_id, role):
    body = get_body()
    comp = req_str(body, "competitor_part_number")
    product_id = req_str(body, "product_id")
    if product_id not in store.products:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {product_id} not found")
    iclass = req_enum(body, "interchange_class", ("EXACT", "DIMENSIONAL", "FUNCTIONAL"))
    mn = req_num(body, "min_shaft_diameter_mm")
    mx = req_num(body, "max_shaft_diameter_mm")
    rec = {
        "id": new_id(),
        "competitor_part_number": comp,
        "product_id": product_id,
        "interchange_class": iclass,
        "min_shaft_diameter_mm": mn,
        "max_shaft_diameter_mm": mx,
        "requires_engineering_review": iclass == "FUNCTIONAL",
    }
    rec["_seq"] = store.next_seq()
    rec["created_at"] = now()
    store.interchanges[rec["id"]] = rec
    return ok(serialize("InterchangeRecord", rec), 201)


@bp.route("/motion/interchange-records", methods=["GET"])
@require_any
def list_interchanges(user_id, role):
    items = list(store.interchanges.values())
    q = request.args
    if q.get("product_id") is not None:
        items = [r for r in items if r["product_id"] == q["product_id"]]
    if q.get("competitor_part_number") is not None:
        items = [r for r in items if r["competitor_part_number"] == q["competitor_part_number"]]
    if q.get("shaft_diameter_mm") is not None:
        try:
            probe = float(q["shaft_diameter_mm"])
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "shaft_diameter_mm must be a number")
        items = [r for r in items
                 if r["min_shaft_diameter_mm"] <= probe <= r["max_shaft_diameter_mm"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("InterchangeRecord", page), limit, offset, total)


@bp.route("/motion/interchange-records/<iid>", methods=["GET"])
@require_any
def get_interchange(user_id, role, iid):
    rec = store.interchanges.get(iid)
    if rec is None:
        raise err("ERR_INTERCHANGE_NOT_FOUND", f"interchange record {iid} not found")
    return ok(serialize("InterchangeRecord", rec))


# ------------------------------------------------------------- price files --

@bp.route("/motion/price-files", methods=["POST"])
@require_roles("PricingAnalyst")
def create_price_file(user_id, role):
    body = get_body()
    # body FK existence (priority 3)
    product_id = req_str(body, "product_id")
    product = store.products.get(product_id)
    if product is None:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {product_id} not found")
    # shape (priority 7)
    new_price = req_int(body, "new_list_price_cents", minimum=0)
    effective_at = req_dt(body, "effective_at")
    expected_version = req_int(body, "expected_product_version")
    # OCC
    if expected_version != product["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_product_version does not match the product's current version")
    # temporal (priority 8): strictly in the future
    if effective_at <= now():
        raise err("ERR_EFFECTIVE_AT_IN_PAST", "effective_at must be strictly in the future")
    # create-with-supersede: prior PENDING file of same product -> SUPERSEDED
    for other in store.price_files.values():
        if other["product_id"] == product_id and other["status"] == "PENDING":
            other["status"] = "SUPERSEDED"
            touch(other)
    rec = stamp_new({
        "id": new_id(),
        "product_id": product_id,
        "new_list_price_cents": new_price,
        "effective_at": effective_at,
        "published_by": user_id,
        "status": "PENDING",
        "_took_effect": False,
    })
    store.price_files[rec["id"]] = rec
    touch(product)  # publish bumps Product.version
    return ok(serialize("PriceFileVersion", rec), 201)


@bp.route("/motion/price-files", methods=["GET"])
@require_any
def list_price_files(user_id, role):
    items = list(store.price_files.values())
    q = request.args
    if q.get("product_id") is not None:
        items = [f for f in items if f["product_id"] == q["product_id"]]
    if q.get("status") is not None:
        items = [f for f in items if f["status"] == q["status"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("PriceFileVersion", page), limit, offset, total)


@bp.route("/motion/price-files/<fid>", methods=["GET"])
@require_any
def get_price_file(user_id, role, fid):
    rec = store.price_files.get(fid)
    if rec is None:
        raise err("ERR_PRICE_FILE_NOT_FOUND", f"price file {fid} not found")
    return ok(serialize("PriceFileVersion", rec))


@bp.route("/motion/price-files/<fid>/cancel", methods=["POST"])
@require_roles("PricingAnalyst")
def cancel_price_file(user_id, role, fid):
    rec = store.price_files.get(fid)
    if rec is None:
        raise err("ERR_PRICE_FILE_NOT_FOUND", f"price file {fid} not found")
    if rec["status"] != "PENDING":
        raise err("ERR_PRICE_FILE_NOT_PENDING", "cancel requires price file PENDING")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(serialize("PriceFileVersion", rec))
