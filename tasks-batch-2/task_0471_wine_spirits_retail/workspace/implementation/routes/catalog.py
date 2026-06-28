"""Catalog: Products, Vintages, InventoryLots and the vintage state machine
(PRD §3.1)."""
import app as A
import calculations as calc
import errors
import middleware
import response
import services
from app import app
from db import store


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@app.route("/products", methods=["POST"])
def create_product():
    middleware.require_roles({A.R_ADMIN})
    body = A.get_body()
    sku = A.require_str(body, "sku")
    name = A.require_str(body, "name")
    category = A.require_str(body, "category")
    container = A.require_str(body, "container_type")
    bottle_ml = A.require_int(body, "bottle_volume_ml")
    abv = A.require_field(body, "abv_pct")
    is_allocated = body.get("is_allocated", False)

    if category not in A.PRODUCT_CATEGORIES:
        raise errors.invalid_request("Invalid category.")
    if container not in A.CONTAINER_TYPES:
        raise errors.invalid_request("Invalid container_type.")
    if bottle_ml < 1:
        raise errors.invalid_request("bottle_volume_ml must be >= 1.")
    if isinstance(abv, bool) or not isinstance(abv, (int, float)):
        raise errors.missing_field("abv_pct must be a number.")
    if abv < 0 or abv > 95:
        raise errors.invalid_request("abv_pct must be in [0, 95].")
    if not isinstance(is_allocated, bool):
        raise errors.invalid_request("is_allocated must be a boolean.")
    # GROWLER/KEG require matching draft container.
    if category == "GROWLER" and container != "GROWLER_FILL":
        raise errors.invalid_request("GROWLER category requires GROWLER_FILL container.")
    if category == "KEG" and container != "KEG_HALF_BBL":
        raise errors.invalid_request("KEG category requires KEG_HALF_BBL container.")

    for p in store.products.values():
        if p["sku"] == sku:
            raise errors.invalid_request("sku must be unique.")

    rec = {
        "sku": sku,
        "name": name,
        "category": category,
        "container_type": container,
        "bottle_volume_ml": bottle_ml,
        "abv_pct": abv,
        "min_purchase_age": calc.minimum_purchase_age(category, abv),
        "is_allocated": is_allocated,
        "status": "ACTIVE",
    }
    A.stamp_create(rec)
    store.products[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.products, pid)
    return response.object_response(A.public(rec))


@app.route("/products", methods=["GET"])
def list_products():
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.products.values())
    cat = A.request.args.get("category")
    status = A.request.args.get("status")
    if cat is not None:
        items = [p for p in items if p["category"] == cat]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Vintages
# ---------------------------------------------------------------------------
@app.route("/products/<pid>/vintages", methods=["POST"])
def create_vintage(pid):
    middleware.require_roles({A.R_ADMIN})
    product = A.get_or_404(store.products, pid)
    body = A.get_body()
    vintage_year = A.require_int(body, "vintage_year")
    list_price = A.require_int(body, "list_price_cents")
    case_pack = A.require_int(body, "case_pack_size")
    alloc_cap = body.get("allocation_cap_per_customer", None)

    if vintage_year < 1900 or vintage_year > 2100:
        raise errors.invalid_request("vintage_year must be in [1900, 2100].")
    if list_price < 1:
        raise errors.invalid_request("list_price_cents must be >= 1.")
    if case_pack < 1:
        raise errors.invalid_request("case_pack_size must be >= 1.")
    if alloc_cap is not None:
        if isinstance(alloc_cap, bool) or not isinstance(alloc_cap, int):
            raise errors.invalid_request("allocation_cap_per_customer must be an integer or null.")
        if alloc_cap < 1:
            raise errors.invalid_request("allocation_cap_per_customer must be >= 1.")

    # (product_id, vintage_year) unique.
    for v in store.vintages.values():
        if v["product_id"] == pid and v["vintage_year"] == vintage_year:
            raise errors.invalid_request("(product_id, vintage_year) must be unique.")

    rec = {
        "product_id": pid,
        "vintage_year": vintage_year,
        "list_price_cents": list_price,
        "allocation_cap_per_customer": alloc_cap,
        "case_pack_size": case_pack,
        "status": "DRAFT",
        "units_committed": 0,
    }
    A.stamp_create(rec)
    store.vintages[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


@app.route("/vintages/<vid>", methods=["GET"])
def get_vintage(vid):
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.vintages, vid)
    return response.object_response(A.public(rec))


@app.route("/products/<pid>/vintages", methods=["GET"])
def list_product_vintages(pid):
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.products, pid)
    limit, offset = A.get_pagination()
    items = [v for v in store.vintages.values() if v["product_id"] == pid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/vintages/<vid>/release", methods=["POST"])
def release_vintage(vid):
    middleware.require_roles({A.R_ADMIN})
    v = A.get_or_404(store.vintages, vid)
    if v["status"] != "DRAFT":
        raise errors.invalid_state()
    product = store.products.get(v["product_id"])
    if product is None:
        raise errors.not_found()
    if product.get("is_allocated", False):
        raise errors.release_requires_stock()
    has_stock = any(
        lot["qty_on_hand"] >= 1 for lot in services.lots_of_vintage(vid))
    if not has_stock:
        raise errors.release_requires_stock()
    v["status"] = "RELEASED"
    A.touch(v)
    return response.object_response(A.public(v))


@app.route("/vintages/<vid>/open-allocation", methods=["POST"])
def open_allocation(vid):
    middleware.require_roles({A.R_COMPLIANCE})
    v = A.get_or_404(store.vintages, vid)
    if v["status"] != "DRAFT":
        raise errors.invalid_state()
    product = store.products.get(v["product_id"])
    if product is None:
        raise errors.not_found()
    if not product.get("is_allocated", False) or v["allocation_cap_per_customer"] is None:
        raise errors.allocation_open_requires_flag()
    v["status"] = "ALLOCATION_OPEN"
    A.touch(v)
    return response.object_response(A.public(v))


@app.route("/vintages/<vid>/delist", methods=["POST"])
def delist_vintage(vid):
    middleware.require_roles({A.R_ADMIN})
    v = A.get_or_404(store.vintages, vid)
    if v["status"] not in ("RELEASED", "SOLD_OUT", "DRAFT"):
        raise errors.invalid_state()
    # No order line of this vintage in PENDING/COMMITTED reservation state.
    blocked = any(
        L["reservation_state"] in ("PENDING", "COMMITTED")
        for L in services.lines_of_vintage(vid))
    if blocked:
        raise errors.invalid_state("Vintage has active reservations.")
    v["status"] = "DELISTED"
    A.touch(v)
    return response.object_response(A.public(v))


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------
@app.route("/vintages/<vid>/lots", methods=["POST"])
def create_lot(vid):
    middleware.require_roles({A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.vintages, vid)
    body = A.get_body()
    tax_status = A.require_str(body, "tax_status")
    qty_on_hand = A.require_int(body, "qty_on_hand")
    excise = A.require_int(body, "excise_band_cents_per_unit")

    if tax_status not in A.TAX_STATUSES:
        raise errors.invalid_request("tax_status must be BONDED or TAXED.")
    if qty_on_hand < 0:
        raise errors.invalid_request("qty_on_hand must be >= 0.")
    if excise < 0:
        raise errors.invalid_request("excise_band_cents_per_unit must be >= 0.")

    rec = {
        "vintage_id": vid,
        "tax_status": tax_status,
        "qty_on_hand": qty_on_hand,
        "qty_reserved": 0,
        "excise_band_cents_per_unit": excise,
    }
    A.stamp_create(rec)
    store.inventory_lots[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    middleware.require_roles({A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.inventory_lots, lid)
    return response.object_response(A.public(rec))


@app.route("/vintages/<vid>/lots", methods=["GET"])
def list_vintage_lots(vid):
    middleware.require_roles({A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.vintages, vid)
    limit, offset = A.get_pagination()
    items = [lot for lot in store.inventory_lots.values() if lot["vintage_id"] == vid]
    tax_status = A.request.args.get("tax_status")
    if tax_status is not None:
        items = [lot for lot in items if lot["tax_status"] == tax_status]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)
