"""Coin & Precious-Metals Dealer API — Flask reference implementation.

In-memory only. No seeding. Boots clean on every start.
"""
import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import core
from core import (
    db, err, success, error_response, authenticate, get_body, bad_request,
    require_str, require_int, require_number, require_enum, optional_bool,
    parse_dt, paginate, stamp_new, touch, gen_request_id,
    unit_sell_price_cents, unit_buy_payout_cents, sell_cogs_provisional_cents,
    sell_cogs_final_and_consume, aggregate_available_qty, _recompute_lot_status,
    get_spot_for_metal, hedge_unrealized_cents, rhu, _dec,
    METALS, PRODUCT_TYPES, REPORTABLE_THRESHOLD_CENTS,
)
from decimal import Decimal

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------
@app.before_request
def _assign_request_id():
    g.request_id = gen_request_id()


@app.errorhandler(core.ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(e):
    # Undefined route / method → mimic not-found / invalid-request envelope.
    if e.code == 404:
        return error_response("ERR_NOT_FOUND", "resource not found", 404)
    if e.code == 405:
        return error_response("ERR_UNAUTHORIZED", "method not allowed", 405)
    return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)


@app.errorhandler(Exception)
def _handle_uncaught(e):
    return error_response("ERR_INTERNAL", f"internal error: {e}", 500)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        err("ERR_NOT_FOUND", 404, "resource not found")
    return ent


def ref(body, field, collection, required=True):
    """Resolve a body foreign key. Missing/malformed → 400; unresolved → 404."""
    val = body.get(field)
    if val is None:
        if required:
            bad_request(f"'{field}' is required")
        return None
    if not isinstance(val, str):
        bad_request(f"'{field}' must be a string id")
    ent = collection.get(val)
    if ent is None:
        err("ERR_NOT_FOUND", 404, f"referenced {field} does not exist")
    return ent


# ===========================================================================
# SpotRate
# ===========================================================================
@app.route("/api/spot-rates", methods=["POST"])
def create_spot_rate():
    authenticate({"Trader"})
    body = get_body()
    metal = require_enum(body, "metal", METALS)
    price = require_int(body, "price_per_troy_oz_cents", minimum=1)
    if get_spot_for_metal(metal) is not None:
        bad_request("a spot rate for this metal already exists")
    sr = stamp_new({"metal": metal, "price_per_troy_oz_cents": price})
    db.spot_rates[sr["id"]] = sr
    return success(sr, 201)


@app.route("/api/spot-rates/<sid>", methods=["PUT"])
def update_spot_rate(sid):
    authenticate({"Trader"})
    sr = get_or_404(db.spot_rates, sid)
    body = get_body()
    price = require_int(body, "price_per_troy_oz_cents", minimum=1)
    sr["price_per_troy_oz_cents"] = price
    touch(sr)
    return success(sr, 200)


@app.route("/api/spot-rates/<sid>", methods=["GET"])
def get_spot_rate(sid):
    authenticate({"Trader", "SalesAgent", "ComplianceOfficer", "Customer"})
    sr = get_or_404(db.spot_rates, sid)
    return success(sr, 200)


# ===========================================================================
# Product
# ===========================================================================
@app.route("/api/products", methods=["POST"])
def create_product():
    authenticate({"Trader"})
    body = get_body()
    sku = require_str(body, "sku")
    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    metal = require_enum(body, "metal", METALS)
    weight = require_number(body, "weight_troy_oz", gt=0)
    purity = require_number(body, "purity", gt=0, le=1)
    min_sell_spread = require_number(body, "min_sell_spread_pct", ge=0, lt=1)
    buy_spread = require_number(body, "buy_spread_pct", ge=0, lt=1)
    premium = 0
    if body.get("numismatic_premium_cents") is not None:
        premium = require_int(body, "numismatic_premium_cents", minimum=0)
    ira_eligible = optional_bool(body, "ira_eligible", default=False)

    if any(p["sku"] == sku for p in db.products.values()):
        bad_request("sku already exists")
    if product_type == "BULLION" and premium > 0:
        err("ERR_BULLION_PREMIUM_FORBIDDEN", 422,
            "a BULLION product must have numismatic_premium_cents == 0")

    prod = stamp_new({
        "sku": sku,
        "product_type": product_type,
        "metal": metal,
        "weight_troy_oz": weight,
        "purity": purity,
        "min_sell_spread_pct": min_sell_spread,
        "buy_spread_pct": buy_spread,
        "numismatic_premium_cents": premium,
        "ira_eligible": ira_eligible,
    })
    db.products[prod["id"]] = prod
    return success(prod, 201)


@app.route("/api/products/<pid>", methods=["GET"])
def get_product(pid):
    authenticate({"Trader", "SalesAgent", "ComplianceOfficer", "Customer"})
    prod = get_or_404(db.products, pid)
    return success(prod, 200)


# ===========================================================================
# InventoryLot
# ===========================================================================
@app.route("/api/inventory-lots", methods=["POST"])
def create_inventory_lot():
    authenticate({"Trader"})
    body = get_body()
    product = ref(body, "product_id", db.products)
    total_qty = require_int(body, "total_qty", minimum=1)
    cost = require_int(body, "acquisition_unit_cost_cents", minimum=0)
    lot = stamp_new({
        "product_id": product["id"],
        "total_qty": total_qty,
        "available_qty": total_qty,
        "reserved_qty": 0,
        "sold_qty": 0,
        "acquisition_unit_cost_cents": cost,
        "status": "AVAILABLE",
    })
    db.inventory_lots[lot["id"]] = lot
    return success(lot, 201)


@app.route("/api/inventory-lots/<lid>", methods=["GET"])
def get_inventory_lot(lid):
    authenticate({"Trader", "SalesAgent", "ComplianceOfficer"})
    lot = get_or_404(db.inventory_lots, lid)
    return success(lot, 200)


@app.route("/api/inventory-lots", methods=["GET"])
def list_inventory_lots():
    authenticate({"Trader", "SalesAgent", "ComplianceOfficer"})
    items = list(db.inventory_lots.values())
    pid = request.args.get("product_id")
    if pid is not None:
        items = [x for x in items if x["product_id"] == pid]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/api/customers", methods=["POST"])
def create_customer():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    body = get_body()
    full_name = require_str(body, "full_name")
    id_on_file = optional_bool(body, "id_document_on_file", default=False)
    cust = stamp_new({
        "full_name": full_name,
        "id_document_on_file": id_on_file,
        "lifetime_buy_payout_cents": 0,
        "store_credit_cents": 0,
    })
    db.customers[cust["id"]] = cust
    return success(cust, 201)


@app.route("/api/customers/<cid>", methods=["PATCH"])
def patch_customer(cid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    cust = get_or_404(db.customers, cid)
    body = get_body()
    if "id_document_on_file" in body and body["id_document_on_file"] is not None:
        if not isinstance(body["id_document_on_file"], bool):
            bad_request("'id_document_on_file' must be a boolean")
        cust["id_document_on_file"] = body["id_document_on_file"]
    touch(cust)
    return success(cust, 200)


@app.route("/api/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authenticate({"SalesAgent", "ComplianceOfficer", "Customer"})
    cust = get_or_404(db.customers, cid)
    return success(cust, 200)


# ===========================================================================
# IRAAccount
# ===========================================================================
@app.route("/api/ira-accounts", methods=["POST"])
def create_ira_account():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    customer = ref(body, "customer_id", db.customers)
    custodian_name = require_str(body, "custodian_name")
    custodian_ref = require_str(body, "custodian_account_ref")
    acct = stamp_new({
        "customer_id": customer["id"],
        "custodian_name": custodian_name,
        "custodian_account_ref": custodian_ref,
        "status": "PENDING",
        "allocated_value_cents": 0,
    })
    db.ira_accounts[acct["id"]] = acct
    return success(acct, 201)


@app.route("/api/ira-accounts/<aid>/approve", methods=["POST"])
def approve_ira_account(aid):
    authenticate({"ComplianceOfficer"})
    acct = get_or_404(db.ira_accounts, aid)
    if acct["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "IRA account is not PENDING")
    customer = db.customers.get(acct["customer_id"])
    if not customer or not customer["id_document_on_file"]:
        err("ERR_ID_REQUIRED_FOR_REPORTABLE", 422,
            "owning customer has no id_document_on_file")
    acct["status"] = "ACTIVE"
    touch(acct)
    return success(acct, 200)


@app.route("/api/ira-accounts/<aid>/close", methods=["POST"])
def close_ira_account(aid):
    authenticate({"ComplianceOfficer"})
    acct = get_or_404(db.ira_accounts, aid)
    if acct["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "IRA account is not ACTIVE")
    acct["status"] = "CLOSED"
    touch(acct)
    return success(acct, 200)


@app.route("/api/ira-accounts/<aid>", methods=["GET"])
def get_ira_account(aid):
    authenticate({"ComplianceOfficer", "SalesAgent"})
    acct = get_or_404(db.ira_accounts, aid)
    return success(acct, 200)


@app.route("/api/ira-accounts", methods=["GET"])
def list_ira_accounts():
    authenticate({"ComplianceOfficer", "SalesAgent"})
    items = list(db.ira_accounts.values())
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [x for x in items if x["customer_id"] == cid]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# SellOrder
# ===========================================================================
@app.route("/api/sell-orders", methods=["POST"])
def create_sell_order():
    authenticate({"SalesAgent"})
    body = get_body()
    customer = ref(body, "customer_id", db.customers)
    product = ref(body, "product_id", db.products)
    ira = ref(body, "ira_account_id", db.ira_accounts, required=False)
    # IRA guards (priority 8 then 9)
    if ira is not None:
        if ira["status"] != "ACTIVE":
            err("ERR_IRA_NOT_ACTIVE", 422, "referenced IRA account is not ACTIVE")
        if not product["ira_eligible"]:
            err("ERR_PRODUCT_NOT_IRA_ELIGIBLE", 422, "product is not IRA-eligible")
    quantity = require_int(body, "quantity", minimum=1)

    spot = get_spot_for_metal(product["metal"])
    if spot is None:
        bad_request("no spot rate for the product's metal")
    unit_price = unit_sell_price_cents(product, spot)
    total = unit_price * quantity
    provisional = sell_cogs_provisional_cents(product["id"], quantity)

    order = stamp_new({
        "customer_id": customer["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "ira_account_id": ira["id"] if ira is not None else None,
        "quoted_unit_price_cents": unit_price,
        "provisional_cogs_cents": provisional,
        "final_cogs_cents": None,
        "total_price_cents": total,
        "realized_margin_cents": None,
        "status": "PLACED",
    })
    db.sell_orders[order["id"]] = order
    return success(order, 201)


@app.route("/api/sell-orders/<oid>/settle", methods=["POST"])
def settle_sell_order(oid):
    authenticate({"SalesAgent"})
    order = get_or_404(db.sell_orders, oid)
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "sell order is not PLACED")
    # inventory sufficiency (PRD §3.3 prose: inventory before IRA)
    if aggregate_available_qty(order["product_id"]) < order["quantity"]:
        err("ERR_INSUFFICIENT_INVENTORY", 422, "insufficient available inventory")
    if order["ira_account_id"] is not None:
        ira = db.ira_accounts.get(order["ira_account_id"])
        if ira is None or ira["status"] != "ACTIVE":
            err("ERR_IRA_NOT_ACTIVE", 422, "referenced IRA account is not ACTIVE")

    final_cogs, _consumed = sell_cogs_final_and_consume(
        order["product_id"], order["quantity"], commit=True)
    order["final_cogs_cents"] = final_cogs
    order["realized_margin_cents"] = order["total_price_cents"] - final_cogs
    if order["ira_account_id"] is not None:
        ira = db.ira_accounts[order["ira_account_id"]]
        ira["allocated_value_cents"] += order["total_price_cents"]
        touch(ira)
    order["status"] = "SETTLED"
    touch(order)
    return success(order, 200)


@app.route("/api/sell-orders/<oid>/cancel", methods=["POST"])
def cancel_sell_order(oid):
    authenticate({"SalesAgent"})
    order = get_or_404(db.sell_orders, oid)
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "sell order is not PLACED")
    order["status"] = "CANCELLED"
    touch(order)
    return success(order, 200)


@app.route("/api/sell-orders/<oid>", methods=["GET"])
def get_sell_order(oid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    order = get_or_404(db.sell_orders, oid)
    return success(order, 200)


@app.route("/api/sell-orders", methods=["GET"])
def list_sell_orders():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    items = list(db.sell_orders.values())
    for key in ("customer_id", "product_id", "ira_account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# BuyOrder
# ===========================================================================
@app.route("/api/buy-orders", methods=["POST"])
def create_buy_order():
    authenticate({"SalesAgent"})
    body = get_body()
    customer = ref(body, "customer_id", db.customers)
    product = ref(body, "product_id", db.products)
    quantity = require_int(body, "quantity", minimum=1)

    spot = get_spot_for_metal(product["metal"])
    if spot is None:
        bad_request("no spot rate for the product's metal")
    unit_payout = unit_buy_payout_cents(product, spot)
    total = unit_payout * quantity
    reportable = total >= REPORTABLE_THRESHOLD_CENTS

    order = stamp_new({
        "customer_id": customer["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "quoted_unit_payout_cents": unit_payout,
        "total_payout_cents": total,
        "reportable": reportable,
        "status": "PLACED",
        "_reportable_approved": False,
    })
    db.buy_orders[order["id"]] = order
    return success(order, 201)


@app.route("/api/buy-orders/<oid>/approve-reportable", methods=["POST"])
def approve_reportable_buy_order(oid):
    authenticate({"ComplianceOfficer"})
    order = get_or_404(db.buy_orders, oid)
    order["_reportable_approved"] = True
    touch(order)
    return success(order, 200)


@app.route("/api/buy-orders/<oid>/settle", methods=["POST"])
def settle_buy_order(oid):
    authenticate({"SalesAgent"})
    order = get_or_404(db.buy_orders, oid)
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "buy order is not PLACED")
    if order["reportable"]:
        customer = db.customers.get(order["customer_id"])
        if customer is None or not customer["id_document_on_file"]:
            err("ERR_ID_REQUIRED_FOR_REPORTABLE", 422,
                "reportable buy requires customer id_document_on_file")
        if not order.get("_reportable_approved"):
            err("ERR_REPORTABLE_NOT_APPROVED", 422,
                "reportable buy has not been compliance-approved")

    # create a new inventory lot from the acquired stock
    lot = stamp_new({
        "product_id": order["product_id"],
        "total_qty": order["quantity"],
        "available_qty": order["quantity"],
        "reserved_qty": 0,
        "sold_qty": 0,
        "acquisition_unit_cost_cents": order["quoted_unit_payout_cents"],
        "status": "AVAILABLE",
    })
    db.inventory_lots[lot["id"]] = lot

    customer = db.customers[order["customer_id"]]
    customer["lifetime_buy_payout_cents"] += order["total_payout_cents"]
    touch(customer)

    order["status"] = "SETTLED"
    touch(order)
    return success(order, 200)


@app.route("/api/buy-orders/<oid>/reject", methods=["POST"])
def reject_buy_order(oid):
    authenticate({"ComplianceOfficer"})
    order = get_or_404(db.buy_orders, oid)
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "buy order is not PLACED")
    order["status"] = "REJECTED"
    touch(order)
    return success(order, 200)


@app.route("/api/buy-orders/<oid>", methods=["GET"])
def get_buy_order(oid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    order = get_or_404(db.buy_orders, oid)
    return success(order, 200)


@app.route("/api/buy-orders", methods=["GET"])
def list_buy_orders():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    items = list(db.buy_orders.values())
    for key in ("customer_id", "product_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# Layaway
# ===========================================================================
@app.route("/api/layaways", methods=["POST"])
def create_layaway():
    authenticate({"SalesAgent"})
    body = get_body()
    customer = ref(body, "customer_id", db.customers)
    product = ref(body, "product_id", db.products)
    lot = ref(body, "inventory_lot_id", db.inventory_lots)
    quantity = require_int(body, "quantity", minimum=1)

    if aggregate_available_qty(product["id"]) < quantity:
        err("ERR_INSUFFICIENT_INVENTORY", 422, "insufficient available inventory")

    spot = get_spot_for_metal(product["metal"])
    if spot is None:
        bad_request("no spot rate for the product's metal")
    unit_price = unit_sell_price_cents(product, spot)
    total = unit_price * quantity

    # reserve on the chosen lot
    lot["available_qty"] -= quantity
    lot["reserved_qty"] += quantity
    _recompute_lot_status(lot)
    touch(lot)

    lay = stamp_new({
        "customer_id": customer["id"],
        "product_id": product["id"],
        "inventory_lot_id": lot["id"],
        "quantity": quantity,
        "locked_unit_price_cents": unit_price,
        "total_price_cents": total,
        "amount_paid_cents": 0,
        "status": "ACTIVE",
    })
    db.layaways[lay["id"]] = lay
    return success(lay, 201)


@app.route("/api/layaways/<lid>/deposit", methods=["POST"])
def deposit_layaway(lid):
    user_id, role = authenticate({"Customer"})
    lay = get_or_404(db.layaways, lid)
    # ownership (priority 4)
    if lay["customer_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", 403, "caller does not own this layaway")
    # state (priority 5)
    if lay["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "layaway is not ACTIVE")
    body = get_body()
    # OCC (version before overpayment per PRD §3.5)
    expected = require_int(body, "expected_layaway_version")
    if expected != lay["version"]:
        err("ERR_STALE_VERSION", 412, "expected_layaway_version does not match")
    amount = require_int(body, "amount_cents", minimum=1)
    if lay["amount_paid_cents"] + amount > lay["total_price_cents"]:
        err("ERR_OVERPAYMENT", 422, "deposit would exceed total price")
    lay["amount_paid_cents"] += amount
    touch(lay)
    return success(lay, 200)


@app.route("/api/layaways/<lid>/complete", methods=["POST"])
def complete_layaway(lid):
    authenticate({"SalesAgent"})
    lay = get_or_404(db.layaways, lid)
    if lay["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "layaway is not ACTIVE")
    if lay["amount_paid_cents"] != lay["total_price_cents"]:
        err("ERR_INVALID_STATE", 409, "layaway is not fully paid")
    lot = db.inventory_lots.get(lay["inventory_lot_id"])
    if lot is not None:
        lot["reserved_qty"] -= lay["quantity"]
        lot["sold_qty"] += lay["quantity"]
        _recompute_lot_status(lot)
        touch(lot)
    lay["status"] = "COMPLETED"
    touch(lay)
    return success(lay, 200)


@app.route("/api/layaways/<lid>/default", methods=["POST"])
def default_layaway(lid):
    authenticate({"SalesAgent"})
    lay = get_or_404(db.layaways, lid)
    if lay["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "layaway is not ACTIVE")
    _release_and_credit(lay)
    lay["status"] = "DEFAULTED"
    touch(lay)
    return success(lay, 200)


@app.route("/api/layaways/<lid>/cancel", methods=["POST"])
def cancel_layaway(lid):
    user_id, role = authenticate({"Customer"})
    lay = get_or_404(db.layaways, lid)
    if lay["customer_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", 403, "caller does not own this layaway")
    if lay["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "layaway is not ACTIVE")
    _release_and_credit(lay)
    lay["status"] = "CANCELLED"
    touch(lay)
    return success(lay, 200)


def _release_and_credit(lay):
    """Release reservation back to available_qty and refund deposits to store credit."""
    lot = db.inventory_lots.get(lay["inventory_lot_id"])
    if lot is not None:
        lot["reserved_qty"] -= lay["quantity"]
        lot["available_qty"] += lay["quantity"]
        _recompute_lot_status(lot)
        touch(lot)
    customer = db.customers.get(lay["customer_id"])
    if customer is not None:
        customer["store_credit_cents"] += lay["amount_paid_cents"]
        touch(customer)


@app.route("/api/layaways/<lid>", methods=["GET"])
def get_layaway(lid):
    authenticate({"SalesAgent", "ComplianceOfficer", "Customer"})
    lay = get_or_404(db.layaways, lid)
    return success(lay, 200)


@app.route("/api/layaways", methods=["GET"])
def list_layaways():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    items = list(db.layaways.values())
    for key in ("customer_id", "product_id", "inventory_lot_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# Consignment
# ===========================================================================
@app.route("/api/consignments", methods=["POST"])
def create_consignment():
    authenticate({"SalesAgent"})
    body = get_body()
    customer = ref(body, "customer_id", db.customers)
    description = require_str(body, "description")
    reserve = require_int(body, "reserve_price_cents", minimum=0)
    commission = require_number(body, "commission_pct", ge=0, lt=1)
    buyer_premium = require_number(body, "buyer_premium_pct", ge=0, lt=1)
    session = ref(body, "auction_session_id", db.auction_sessions, required=False)
    cons = stamp_new({
        "customer_id": customer["id"],
        "description": description,
        "reserve_price_cents": reserve,
        "commission_pct": commission,
        "buyer_premium_pct": buyer_premium,
        "auction_session_id": session["id"] if session is not None else None,
        "hammer_price_cents": None,
        "status": "INTAKE",
    })
    db.consignments[cons["id"]] = cons
    return success(cons, 201)


@app.route("/api/consignments/<cid>/list", methods=["POST"])
def list_consignment(cid):
    authenticate({"SalesAgent"})
    cons = get_or_404(db.consignments, cid)
    body = get_body()
    session = ref(body, "auction_session_id", db.auction_sessions)
    if cons["status"] != "INTAKE":
        err("ERR_INVALID_STATE", 409, "consignment is not INTAKE")
    if session["status"] != "SCHEDULED":
        err("ERR_SESSION_NOT_SCHEDULED", 422, "auction session is not SCHEDULED")
    cons["auction_session_id"] = session["id"]
    cons["status"] = "LISTED"
    touch(cons)
    return success(cons, 200)


@app.route("/api/consignments/<cid>/record-sale", methods=["POST"])
def record_sale_consignment(cid):
    authenticate({"SalesAgent"})
    cons = get_or_404(db.consignments, cid)
    if cons["status"] != "LISTED":
        err("ERR_INVALID_STATE", 409, "consignment is not LISTED")
    body = get_body()
    expected = require_int(body, "expected_consignment_version")
    if expected != cons["version"]:
        err("ERR_STALE_VERSION", 412, "expected_consignment_version does not match")
    hammer = require_int(body, "hammer_price_cents", minimum=0)
    if hammer < cons["reserve_price_cents"]:
        err("ERR_RESERVE_NOT_MET", 422, "hammer price is below reserve")
    cons["hammer_price_cents"] = hammer
    cons["status"] = "SOLD"
    touch(cons)
    return success(cons, 200)


@app.route("/api/consignments/<cid>/return", methods=["POST"])
def return_consignment(cid):
    authenticate({"SalesAgent"})
    cons = get_or_404(db.consignments, cid)
    if cons["status"] != "LISTED":
        err("ERR_INVALID_STATE", 409, "consignment is not LISTED")
    cons["status"] = "RETURNED"
    touch(cons)
    return success(cons, 200)


@app.route("/api/consignments/<cid>", methods=["GET"])
def get_consignment(cid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    cons = get_or_404(db.consignments, cid)
    return success(cons, 200)


@app.route("/api/consignments", methods=["GET"])
def list_consignments():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    items = list(db.consignments.values())
    for key in ("customer_id", "auction_session_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# HedgePosition
# ===========================================================================
@app.route("/api/hedge-positions", methods=["POST"])
def create_hedge_position():
    authenticate({"Trader"})
    body = get_body()
    metal = require_enum(body, "metal", METALS)
    short = require_number(body, "short_troy_oz", gt=0)
    spot = get_spot_for_metal(metal)
    if spot is None:
        bad_request("no spot rate for the metal")
    pos = stamp_new({
        "metal": metal,
        "short_troy_oz": short,
        "entry_spot_cents": spot["price_per_troy_oz_cents"],
        "exit_spot_cents": None,
        "unrealized_pnl_cents": 0,
        "realized_pnl_cents": None,
        "status": "OPEN",
    })
    db.hedge_positions[pos["id"]] = pos
    return success(pos, 201)


@app.route("/api/hedge-positions/<hid>/close", methods=["POST"])
def close_hedge_position(hid):
    authenticate({"Trader"})
    pos = get_or_404(db.hedge_positions, hid)
    if pos["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "hedge position is not OPEN")
    spot = get_spot_for_metal(pos["metal"])
    if spot is None:
        bad_request("no spot rate for the metal")
    exit_spot = spot["price_per_troy_oz_cents"]
    pos["exit_spot_cents"] = exit_spot
    pos["realized_pnl_cents"] = rhu(
        _dec(pos["entry_spot_cents"] - exit_spot) * _dec(pos["short_troy_oz"]))
    pos["unrealized_pnl_cents"] = 0
    pos["status"] = "CLOSED"
    touch(pos)
    return success(pos, 200)


@app.route("/api/hedge-positions/<hid>", methods=["GET"])
def get_hedge_position(hid):
    authenticate({"Trader"})
    pos = get_or_404(db.hedge_positions, hid)
    if pos["status"] == "OPEN":
        pos["unrealized_pnl_cents"] = hedge_unrealized_cents(pos)
    return success(pos, 200)


# ===========================================================================
# Settlement
# ===========================================================================
@app.route("/api/settlements", methods=["POST"])
def create_settlement():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    cons = ref(body, "consignment_id", db.consignments)
    if cons["status"] != "SOLD":
        err("ERR_INVALID_STATE", 409, "consignment is not SOLD")
    hammer = cons["hammer_price_cents"]
    commission = rhu(_dec(hammer) * _dec(cons["commission_pct"]))
    buyer_premium = rhu(_dec(hammer) * _dec(cons["buyer_premium_pct"]))
    seller_proceeds = hammer - commission
    dealer_revenue = commission + buyer_premium

    settlement = stamp_new({
        "consignment_id": cons["id"],
        "hammer_price_cents": hammer,
        "commission_cents": commission,
        "buyer_premium_cents": buyer_premium,
        "seller_proceeds_cents": seller_proceeds,
        "dealer_revenue_cents": dealer_revenue,
    })
    db.settlements[settlement["id"]] = settlement

    customer = db.customers.get(cons["customer_id"])
    if customer is not None:
        customer["store_credit_cents"] += seller_proceeds
        touch(customer)

    return success(settlement, 201)


@app.route("/api/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    authenticate({"ComplianceOfficer", "SalesAgent"})
    settlement = get_or_404(db.settlements, sid)
    return success(settlement, 200)


@app.route("/api/settlements", methods=["GET"])
def list_settlements():
    authenticate({"ComplianceOfficer", "SalesAgent"})
    items = list(db.settlements.values())
    cid = request.args.get("consignment_id")
    if cid is not None:
        items = [x for x in items if x["consignment_id"] == cid]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# Appraiser
# ===========================================================================
@app.route("/api/appraisers", methods=["POST"])
def create_appraiser():
    authenticate({"SalesAgent"})
    body = get_body()
    name = require_str(body, "name")
    specialty = require_enum(body, "specialty_metal", METALS)
    appr = stamp_new({"name": name, "specialty_metal": specialty})
    db.appraisers[appr["id"]] = appr
    return success(appr, 201)


@app.route("/api/appraisers/<aid>", methods=["GET"])
def get_appraiser(aid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    appr = get_or_404(db.appraisers, aid)
    return success(appr, 200)


# ===========================================================================
# AppraisalAppointment
# ===========================================================================
@app.route("/api/appraisal-appointments", methods=["POST"])
def create_appraisal_appointment():
    authenticate({"SalesAgent"})
    body = get_body()
    appraiser = ref(body, "appraiser_id", db.appraisers)
    consignment = ref(body, "consignment_id", db.consignments)
    start_at = parse_dt(body, "start_at")
    end_at = parse_dt(body, "end_at")
    if not (end_at > start_at):
        bad_request("end_at must be after start_at")
    # closed-interval overlap for same appraiser among BOOKED appointments
    for appt in db.appraisal_appointments.values():
        if appt["appraiser_id"] != appraiser["id"] or appt["status"] != "BOOKED":
            continue
        e_start = parse_iso_stored(appt["start_at"])
        e_end = parse_iso_stored(appt["end_at"])
        if start_at <= e_end and e_start <= end_at:
            err("ERR_APPRAISER_DOUBLE_BOOKED", 409,
                "appraiser is already booked in this interval")
    appt = stamp_new({
        "appraiser_id": appraiser["id"],
        "consignment_id": consignment["id"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "BOOKED",
    })
    db.appraisal_appointments[appt["id"]] = appt
    return success(appt, 201)


@app.route("/api/appraisal-appointments/<aid>/cancel", methods=["POST"])
def cancel_appraisal_appointment(aid):
    authenticate({"SalesAgent"})
    appt = get_or_404(db.appraisal_appointments, aid)
    if appt["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "appointment is not BOOKED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success(appt, 200)


@app.route("/api/appraisal-appointments/<aid>", methods=["GET"])
def get_appraisal_appointment(aid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    appt = get_or_404(db.appraisal_appointments, aid)
    return success(appt, 200)


@app.route("/api/appraisal-appointments", methods=["GET"])
def list_appraisal_appointments():
    authenticate({"SalesAgent", "ComplianceOfficer"})
    items = list(db.appraisal_appointments.values())
    for key in ("appraiser_id", "consignment_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, meta = paginate(items)
    return success(page, 200, pagination=meta)


# ===========================================================================
# AuctionSession
# ===========================================================================
@app.route("/api/auction-sessions", methods=["POST"])
def create_auction_session():
    authenticate({"SalesAgent"})
    body = get_body()
    room = require_str(body, "room")
    start = parse_dt(body, "scheduled_start")
    end = parse_dt(body, "scheduled_end")
    if not (end > start):
        bad_request("scheduled_end must be after scheduled_start")
    # half-open overlap for same room among SCHEDULED sessions
    for sess in db.auction_sessions.values():
        if sess["room"] != room or sess["status"] != "SCHEDULED":
            continue
        e_start = parse_iso_stored(sess["scheduled_start"])
        e_end = parse_iso_stored(sess["scheduled_end"])
        if start < e_end and e_start < end:
            err("ERR_ROOM_DOUBLE_BOOKED", 409,
                "room is already booked in this interval")
    sess = stamp_new({
        "room": room,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
    })
    db.auction_sessions[sess["id"]] = sess
    return success(sess, 201)


@app.route("/api/auction-sessions/<sid>/close", methods=["POST"])
def close_auction_session(sid):
    authenticate({"SalesAgent"})
    sess = get_or_404(db.auction_sessions, sid)
    if sess["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "auction session is not SCHEDULED")
    sess["status"] = "CLOSED"
    touch(sess)
    return success(sess, 200)


@app.route("/api/auction-sessions/<sid>", methods=["GET"])
def get_auction_session(sid):
    authenticate({"SalesAgent", "ComplianceOfficer"})
    sess = get_or_404(db.auction_sessions, sid)
    return success(sess, 200)


# ---------------------------------------------------------------------------
# datetime helper for stored ISO strings
# ---------------------------------------------------------------------------
def parse_iso_stored(raw):
    from datetime import datetime, timezone
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
