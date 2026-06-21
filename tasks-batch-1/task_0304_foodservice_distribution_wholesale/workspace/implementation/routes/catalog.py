"""Catalog & infrastructure routes: distributors, clock, warehouses, routes,
products, price-tiers, inventory-lots."""
from flask import Blueprint

import db
import errors
import middleware
import models
import response
from routes.listing import list_response
from services import lookup, serialize
from services.clocks import parse_iso

bp = Blueprint("catalog", __name__)

READ_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}


# --- Distributor -------------------------------------------------------------

@bp.route("/distributors", methods=["POST"])
def create_distributor():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    name = models.require_str(body, "name")
    with db.lock:
        rec = models.base_record({
            "name": name,
            "current_utc": "1970-01-01T00:00:00.000Z",
            "catalog_revision": 0,
        })
        db.distributors[rec["id"]] = rec
        return response.object_response(serialize.distributor(rec), 201)


@bp.route("/distributors/<distributor_id>", methods=["GET"])
def get_distributor(distributor_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.distributor(distributor_id)
    return response.object_response(serialize.distributor(rec), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    distributor_id = models.require_str(body, "distributor_id")
    to_iso = models.require_str(body, "to_iso8601")
    with db.lock:
        dist = lookup.distributor(distributor_id)
        # Validate the supplied instant is a well-formed ISO 8601 datetime.
        parse_iso(to_iso, "to_iso8601")
        dist["current_utc"] = to_iso
        models.touch(dist)
        # AR sweep: any ACTIVE customer whose ar_balance > credit_limit -> hold.
        for cust in db.customers.values():
            if cust["distributor_id"] != distributor_id:
                continue
            if cust["ar_status"] == "ACTIVE" and cust["ar_balance_cents"] > cust["credit_limit_cents"]:
                cust["ar_status"] = "CREDIT_HOLD"
                models.touch(cust)
        return response.object_response(serialize.distributor(dist), 200)


# --- Warehouse ---------------------------------------------------------------

@bp.route("/warehouses", methods=["POST"])
def create_warehouse():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    distributor_id = models.require_str(body, "distributor_id")
    code = models.require_str(body, "code")
    name = models.require_str(body, "name")
    with db.lock:
        lookup.distributor(distributor_id)
        for wh in db.warehouses.values():
            if wh["distributor_id"] == distributor_id and wh["code"] == code:
                raise errors.ApiError(errors.ERR_DUPLICATE_CODE, 409,
                                      "Warehouse code already exists for this distributor.")
        rec = models.base_record({
            "distributor_id": distributor_id, "code": code, "name": name,
        })
        db.warehouses[rec["id"]] = rec
        return response.object_response(serialize.warehouse(rec), 201)


@bp.route("/warehouses/<warehouse_id>", methods=["GET"])
def get_warehouse(warehouse_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.warehouse(warehouse_id)
    return response.object_response(serialize.warehouse(rec), 200)


@bp.route("/warehouses", methods=["GET"])
def list_warehouses():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.warehouses.values(), serialize.warehouse,
                         {"distributor_id": "distributor_id"})


# --- Route -------------------------------------------------------------------

@bp.route("/routes", methods=["POST"])
def create_route():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    distributor_id = models.require_str(body, "distributor_id")
    warehouse_id = models.require_str(body, "warehouse_id")
    code = models.require_str(body, "code")
    delivery_dow = models.require_int(body, "delivery_dow", min_value=0)
    if delivery_dow > 6:
        raise errors.invalid_request("delivery_dow must be between 0 and 6.")
    cutoff_lead_hours = models.require_int(body, "cutoff_lead_hours", min_value=0)
    min_gap = models.opt_int(body, "min_delivery_gap_days", default=0, min_value=0)
    with db.lock:
        lookup.distributor(distributor_id)
        wh = lookup.warehouse(warehouse_id)
        if wh["distributor_id"] != distributor_id:
            raise errors.cross_distributor("Warehouse belongs to a different distributor.")
        for rt in db.routes.values():
            if rt["distributor_id"] == distributor_id and rt["code"] == code:
                raise errors.ApiError(errors.ERR_DUPLICATE_CODE, 409,
                                      "Route code already exists for this distributor.")
        rec = models.base_record({
            "distributor_id": distributor_id,
            "warehouse_id": warehouse_id,
            "code": code,
            "delivery_dow": delivery_dow,
            "cutoff_lead_hours": cutoff_lead_hours,
            "min_delivery_gap_days": min_gap,
        })
        db.routes[rec["id"]] = rec
        return response.object_response(serialize.route(rec), 201)


@bp.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.route(route_id)
    return response.object_response(serialize.route(rec), 200)


@bp.route("/routes", methods=["GET"])
def list_routes():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.routes.values(), serialize.route,
                         {"distributor_id": "distributor_id",
                          "warehouse_id": "warehouse_id"})


# --- Product -----------------------------------------------------------------

@bp.route("/products", methods=["POST"])
def create_product():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    distributor_id = models.require_str(body, "distributor_id")
    sku = models.require_str(body, "sku")
    name = models.require_str(body, "name")
    category = models.require_str(body, "category")
    splits_per_case = models.require_int(body, "splits_per_case", min_value=1)
    split_allowed = models.opt_bool(body, "split_allowed", default=True)
    perishable = models.opt_bool(body, "perishable", default=False)
    substitute_product_id = models.opt_str(body, "substitute_product_id", default=None)
    case_cost_cents = models.require_int(body, "case_cost_cents", min_value=0)
    with db.lock:
        dist = lookup.distributor(distributor_id)
        for p in db.products.values():
            if p["distributor_id"] == distributor_id and p["sku"] == sku:
                raise errors.ApiError(errors.ERR_DUPLICATE_SKU, 409,
                                      "Product sku already exists for this distributor.")
        if substitute_product_id is not None:
            sub = lookup.product(substitute_product_id)
            if sub["distributor_id"] != distributor_id:
                raise errors.cross_distributor("Substitute product belongs to a different distributor.")
        rec = models.base_record({
            "distributor_id": distributor_id,
            "sku": sku,
            "name": name,
            "category": category,
            "splits_per_case": splits_per_case,
            "split_allowed": split_allowed,
            "perishable": perishable,
            "substitute_product_id": substitute_product_id,
            "case_cost_cents": case_cost_cents,
            "status": "ACTIVE",
        })
        db.products[rec["id"]] = rec
        dist["catalog_revision"] += 1
        models.touch(dist)
        return response.object_response(serialize.product(rec), 201)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.product(product_id)
    return response.object_response(serialize.product(rec), 200)


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.products.values(), serialize.product,
                         {"distributor_id": "distributor_id",
                          "category": "category",
                          "substitute_product_id": "substitute_product_id"})


@bp.route("/products/<product_id>/discontinue", methods=["POST"])
def discontinue_product(product_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    with db.lock:
        rec = lookup.product(product_id)
        rec["status"] = "DISCONTINUED"
        models.touch(rec)
        return response.object_response(serialize.product(rec), 200)


# --- PriceTier ---------------------------------------------------------------

@bp.route("/price-tiers", methods=["POST"])
def create_price_tier():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    body = middleware.get_json_body()
    product_id = models.require_str(body, "product_id")
    min_cases = models.require_int(body, "min_cases", min_value=1)
    case_price_cents = models.require_int(body, "case_price_cents", min_value=0)
    with db.lock:
        product = lookup.product(product_id)
        for t in db.price_tiers.values():
            if t["product_id"] == product_id and t["min_cases"] == min_cases:
                raise errors.ApiError(errors.ERR_DUPLICATE_TIER, 409,
                                      "A price tier with this min_cases already exists for the product.")
        rec = models.base_record({
            "product_id": product_id,
            "distributor_id": product["distributor_id"],
            "min_cases": min_cases,
            "case_price_cents": case_price_cents,
        })
        db.price_tiers[rec["id"]] = rec
        dist = lookup.distributor(product["distributor_id"])
        dist["catalog_revision"] += 1
        models.touch(dist)
        return response.object_response(serialize.price_tier(rec), 201)


@bp.route("/price-tiers/<price_tier_id>", methods=["GET"])
def get_price_tier(price_tier_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.price_tier(price_tier_id)
    return response.object_response(serialize.price_tier(rec), 200)


@bp.route("/price-tiers", methods=["GET"])
def list_price_tiers():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.price_tiers.values(), serialize.price_tier,
                         {"product_id": "product_id",
                          "distributor_id": "distributor_id"})


# --- InventoryLot ------------------------------------------------------------

@bp.route("/inventory-lots", methods=["POST"])
def create_inventory_lot():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin", "WarehouseOp"})
    body = middleware.get_json_body()
    product_id = models.require_str(body, "product_id")
    warehouse_id = models.require_str(body, "warehouse_id")
    lot_code = models.require_str(body, "lot_code")
    expires_on = models.opt_str(body, "expires_on", default=None)
    on_hand_splits = models.require_int(body, "on_hand_splits", min_value=0)
    with db.lock:
        product = lookup.product(product_id)
        wh = lookup.warehouse(warehouse_id)
        if wh["distributor_id"] != product["distributor_id"]:
            raise errors.cross_distributor("Warehouse belongs to a different distributor than the product.")
        rec = models.base_record({
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "lot_code": lot_code,
            "expires_on": expires_on,
            "on_hand_splits": on_hand_splits,
            "reserved_splits": 0,
        })
        db.inventory_lots[rec["id"]] = rec
        return response.object_response(serialize.inventory_lot(rec), 201)


@bp.route("/inventory-lots/<lot_id>", methods=["GET"])
def get_inventory_lot(lot_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.inventory_lot(lot_id)
    return response.object_response(serialize.inventory_lot(rec), 200)


@bp.route("/inventory-lots", methods=["GET"])
def list_inventory_lots():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.inventory_lots.values(), serialize.inventory_lot,
                         {"product_id": "product_id",
                          "warehouse_id": "warehouse_id"})
