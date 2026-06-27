"""Trading Card & Hobby Game Store API — Flask entry point.

In-memory storage only; state is wiped on every process start. No entities are
seeded, preloaded, or hardcoded — tests build all state via the API.

Validation ordering (PRD §2.9): auth -> authz -> existence -> state (incl. the
banned check for check-in) -> request well-formedness -> quantity/grade bounds
-> domain business constraints.
"""

import os
import socket

# Werkzeug's dev server resolves the host FQDN at startup (for its banner /
# "Running on http://<fqdn>" line). On some hosts socket.getfqdn() stalls for
# ~5s on mDNS reverse resolution (e.g. a "*.local" hostname), which delays the
# socket bind. Under per-test-server isolation the server reboots before every
# test, so a 5s-per-boot stall compounds and can push boot past the runner's
# readiness window, surfacing as "API server could not be restarted". Returning
# a constant FQDN removes the stall; it has no bearing on what the server binds
# to (host/port are explicit) or on request handling.
socket.getfqdn = lambda *args, **kwargs: "localhost"

from flask import Flask, request

import db
import response
from common import (
    authenticate,
    get_body,
    parse_datetime,
    parse_pagination,
    paginate,
    public,
    require_enum,
    require_fields,
    require_int,
    require_owner,
    require_role,
    require_str,
    stamp_create,
    touch,
)
import calculations as calc
import services
from errors import ApiError, err

app = Flask(__name__)

# Domain constants (scaffold §1.5 domain_constants, PRD §3.5).
STORE_TABLE_COUNT = 8
BUFFER_MINUTES = 30
MAX_ROUNDS = 5

CONDITIONS = {"MINT", "NEAR_MINT", "LIGHTLY_PLAYED", "MODERATELY_PLAYED", "DAMAGED"}
PRODUCT_KINDS = {"SINGLE", "SEALED"}
PAYOUT_METHODS = {"STORE_CREDIT", "CASH"}
EVENT_FORMATS = {"STANDARD", "MODERN", "COMMANDER", "DRAFT"}
SERVICE_TIERS = {"ECONOMY", "STANDARD", "EXPRESS"}


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return response.error_response("ERR_INVALID_REQUEST", str(e), 400)


# ===========================================================================
# Helpers
# ===========================================================================

def list_response(store, predicate=None):
    limit, offset = parse_pagination()
    items = list(store.values())
    if predicate is not None:
        items = [e for e in items if predicate(e)]
    page, total = paginate(items, limit, offset)
    return response.array_response([public(e) for e in page], limit, offset, total)


def serialize(entity):
    return public(entity)


# ===========================================================================
# Logical clock (PRD §3.8)
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return response.object_response({})


# ===========================================================================
# Customers (PRD §3.1)
# ===========================================================================

@app.route("/customers", methods=["POST"])
def create_customer():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["display_name", "email"])
    display_name = require_str(body, "display_name")
    email = require_str(body, "email")
    cust = {
        "display_name": display_name,
        "email": email,
        "loyalty_tier": "BRONZE",
        "lifetime_spend_cents": 0,
        "store_credit_balance_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(cust)
    db.customers[cust["id"]] = cust
    return response.object_response(serialize(cust), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer_route(cid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    cust = services.get_customer(cid)
    require_owner(auth, cust["id"])
    return response.object_response(serialize(cust))


@app.route("/customers", methods=["GET"])
def list_customers():
    auth = authenticate()
    require_role(auth, {"StoreManager", "JudgeStaff"})
    email = request.args.get("email")

    def pred(c):
        return email is None or c["email"] == email

    return list_response(db.customers, pred)


@app.route("/customers/<cid>/ban", methods=["POST"])
def ban_customer(cid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    cust = services.get_customer(cid)
    cust["status"] = "BANNED"
    touch(cust)
    return response.object_response(serialize(cust))


@app.route("/customers/<cid>/credit-adjustments", methods=["POST"])
def credit_adjustment(cid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    cust = services.get_customer(cid)
    body = get_body()
    require_fields(body, ["delta_cents"])
    delta = require_int(body, "delta_cents")
    row = services.append_ledger(cust, delta, "MANUAL_ADJUSTMENT", source_entity_id=None)
    return response.object_response(serialize(row), 201)


@app.route("/customers/<cid>/ledger", methods=["GET"])
def list_ledger(cid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    cust = services.get_customer(cid)
    require_owner(auth, cust["id"])
    return list_response(db.ledger_rows, lambda r: r["customer_id"] == cid)


@app.route("/customers/<cid>/registrations", methods=["GET"])
def list_customer_registrations(cid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    cust = services.get_customer(cid)
    require_owner(auth, cust["id"])
    return list_response(db.registrations, lambda r: r["customer_id"] == cid)


# ===========================================================================
# Inventory items (PRD §3.2)
# ===========================================================================

@app.route("/inventory-items", methods=["POST"])
def create_inventory_item():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["title", "product_kind", "market_price_cents"])
    title = require_str(body, "title")
    product_kind = require_enum(body, "product_kind", PRODUCT_KINDS)
    market_price_cents = require_int(body, "market_price_cents")
    if market_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "market_price_cents must be >= 0")
    if "condition" in body and body["condition"] is not None:
        condition = require_enum(body, "condition", CONDITIONS)
    else:
        condition = "NEAR_MINT"
    item = {
        "title": title,
        "product_kind": product_kind,
        "condition": condition,
        "market_price_cents": market_price_cents,
        "quantity_on_hand": 0,
        "quantity_reserved": 0,
    }
    stamp_create(item)
    db.inventory_items[item["id"]] = item
    return response.object_response(serialize(item), 201)


@app.route("/inventory-items/<iid>", methods=["GET"])
def get_inventory_item_route(iid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    item = services.get_inventory_item(iid)
    return response.object_response(serialize(item))


@app.route("/inventory-items", methods=["GET"])
def list_inventory_items():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    kind = request.args.get("product_kind")
    return list_response(db.inventory_items, lambda e: kind is None or e["product_kind"] == kind)


# ===========================================================================
# Buylist submissions + lines (PRD §3.2)
# ===========================================================================

@app.route("/buylist-submissions", methods=["POST"])
def create_buylist_submission():
    auth = authenticate()
    require_role(auth, {"Customer"})
    body = get_body()
    require_fields(body, ["customer_id", "payout_method"])
    customer_id = require_str(body, "customer_id")
    payout_method = require_enum(body, "payout_method", PAYOUT_METHODS)
    require_owner(auth, customer_id)
    services.get_customer(customer_id)
    sub = {
        "customer_id": customer_id,
        "payout_method": payout_method,
        "status": "DRAFT",
        "offered_total_cents": 0,
    }
    stamp_create(sub)
    db.buylist_submissions[sub["id"]] = sub
    return response.object_response(serialize(sub), 201)


@app.route("/buylist-submissions/<sid>", methods=["GET"])
def get_buylist_submission(sid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    sub = services.find_or_404(db.buylist_submissions, sid)
    require_owner(auth, sub["customer_id"])
    return response.object_response(serialize(sub))


@app.route("/buylist-submissions", methods=["GET"])
def list_buylist_submissions():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    customer_id = request.args.get("customer_id")
    if auth.role == "Customer":
        customer_id = auth.user_id
    return list_response(
        db.buylist_submissions,
        lambda s: customer_id is None or s["customer_id"] == customer_id,
    )


@app.route("/buylist-lines", methods=["POST"])
def create_buylist_line():
    auth = authenticate()
    require_role(auth, {"Customer"})
    body = get_body()
    require_fields(body, ["buylist_submission_id", "inventory_item_id", "quantity"])
    submission_id = require_str(body, "buylist_submission_id")
    inventory_item_id = require_str(body, "inventory_item_id")
    quantity = require_int(body, "quantity")
    # Existence (priority 3): FKs validated left to right.
    sub = services.find_or_404(db.buylist_submissions, submission_id)
    require_owner(auth, sub["customer_id"])
    services.get_inventory_item(inventory_item_id)
    # Quantity minimum (priority 7).
    if quantity < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1")
    line = {
        "buylist_submission_id": submission_id,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
        "line_payout_cents": 0,
    }
    stamp_create(line)
    db.buylist_lines[line["id"]] = line
    return response.object_response(serialize(line), 201)


@app.route("/buylist-lines/<lid>", methods=["GET"])
def get_buylist_line(lid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    line = services.find_or_404(db.buylist_lines, lid)
    sub = db.buylist_submissions.get(line["buylist_submission_id"])
    if auth.role == "Customer" and (sub is None or sub["customer_id"] != auth.user_id):
        raise err("ERR_UNAUTHORIZED", "Customer does not own this resource")
    return response.object_response(serialize(line))


@app.route("/buylist-lines", methods=["GET"])
def list_buylist_lines():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    submission_id = request.args.get("buylist_submission_id")
    inventory_item_id = request.args.get("inventory_item_id")

    def pred(line):
        if submission_id is not None and line["buylist_submission_id"] != submission_id:
            return False
        if inventory_item_id is not None and line["inventory_item_id"] != inventory_item_id:
            return False
        if auth.role == "Customer":
            sub = db.buylist_submissions.get(line["buylist_submission_id"])
            if sub is None or sub["customer_id"] != auth.user_id:
                return False
        return True

    return list_response(db.buylist_lines, pred)


def _lines_for_submission(submission_id):
    lines = [l for l in db.buylist_lines.values() if l["buylist_submission_id"] == submission_id]
    lines.sort(key=lambda l: l["_seq"])
    return lines


@app.route("/buylist-submissions/<sid>/submit", methods=["POST"])
def submit_buylist(sid):
    auth = authenticate()
    require_role(auth, {"Customer"})
    sub = services.find_or_404(db.buylist_submissions, sid)
    require_owner(auth, sub["customer_id"])
    # State (priority 4): submit defined only from DRAFT.
    if sub["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Buylist not in DRAFT")
    lines = _lines_for_submission(sid)
    # Empty buylist (priority 11).
    if not lines:
        raise err("ERR_EMPTY_BUYLIST", "Buylist has no lines")
    # Every line quantity >= 1 (priority 7).
    for l in lines:
        if l["quantity"] < 1:
            raise err("ERR_INVALID_QUANTITY", "Line quantity must be >= 1")
    sub["status"] = "SUBMITTED"
    touch(sub)
    return response.object_response(serialize(sub))


@app.route("/buylist-submissions/<sid>/accept", methods=["POST"])
def accept_buylist(sid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    sub = services.find_or_404(db.buylist_submissions, sid)
    if sub["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Buylist not in SUBMITTED")
    lines = _lines_for_submission(sid)
    # Per-line valuation: round per line, then sum (PRD §3.2).
    total = 0
    for l in lines:
        item = db.inventory_items[l["inventory_item_id"]]
        payout = calc.buylist_line_payout(item["market_price_cents"], l["quantity"], sub["payout_method"])
        l["line_payout_cents"] = payout
        touch(l)
        total += payout
    sub["offered_total_cents"] = total
    # Cascade: add each line's quantity to inventory on-hand.
    for l in lines:
        item = db.inventory_items[l["inventory_item_id"]]
        item["quantity_on_hand"] += l["quantity"]
        touch(item)
    sub["status"] = "ACCEPTED"
    touch(sub)
    # Ledger payout only for STORE_CREDIT.
    if sub["payout_method"] == "STORE_CREDIT":
        cust = db.customers[sub["customer_id"]]
        services.append_ledger(cust, total, "BUYLIST_PAYOUT", source_entity_id=sub["id"])
    return response.object_response(serialize(sub))


@app.route("/buylist-submissions/<sid>/reject", methods=["POST"])
def reject_buylist(sid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    sub = services.find_or_404(db.buylist_submissions, sid)
    if sub["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Buylist not in SUBMITTED")
    sub["status"] = "REJECTED"
    touch(sub)
    return response.object_response(serialize(sub))


@app.route("/buylist-submissions/<sid>/void", methods=["POST"])
def void_buylist(sid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    sub = services.find_or_404(db.buylist_submissions, sid)
    if sub["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Buylist not in ACCEPTED")
    lines = _lines_for_submission(sid)
    # Reserved-inventory protection (priority 12): check ALL lines before any
    # mutation (atomicity).
    for l in lines:
        item = db.inventory_items[l["inventory_item_id"]]
        if item["quantity_on_hand"] - l["quantity"] < item["quantity_reserved"]:
            raise err("ERR_INVENTORY_RESERVED", "Void would drive on-hand below reserved")
    for l in lines:
        item = db.inventory_items[l["inventory_item_id"]]
        item["quantity_on_hand"] -= l["quantity"]
        touch(item)
    sub["status"] = "VOIDED"
    touch(sub)
    if sub["payout_method"] == "STORE_CREDIT":
        cust = db.customers[sub["customer_id"]]
        services.append_ledger(cust, -sub["offered_total_cents"], "BUYLIST_PAYOUT", source_entity_id=sub["id"])
    return response.object_response(serialize(sub))


# ===========================================================================
# Release products + pre-orders (PRD §3.3)
# ===========================================================================

@app.route("/release-products", methods=["POST"])
def create_release_product():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["title", "street_date", "allocation_pool", "unit_price_cents", "deposit_required_cents"])
    title = require_str(body, "title")
    street_date = parse_datetime(body, "street_date")
    allocation_pool = require_int(body, "allocation_pool")
    unit_price_cents = require_int(body, "unit_price_cents")
    deposit_required_cents = require_int(body, "deposit_required_cents")
    for name, val in [("allocation_pool", allocation_pool), ("unit_price_cents", unit_price_cents), ("deposit_required_cents", deposit_required_cents)]:
        if val < 0:
            raise err("ERR_INVALID_REQUEST", f"{name} must be >= 0")
    rp = {
        "title": title,
        "street_date": db.iso(street_date),
        "allocation_pool": allocation_pool,
        "unit_price_cents": unit_price_cents,
        "deposit_required_cents": deposit_required_cents,
        "quantity_allocated": 0,
        "status": "PRE_ORDER_OPEN",
    }
    stamp_create(rp)
    db.release_products[rp["id"]] = rp
    return response.object_response(serialize(rp), 201)


@app.route("/release-products/<rid>", methods=["GET"])
def get_release_product(rid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    rp = services.find_or_404(db.release_products, rid)
    return response.object_response(serialize(rp))


@app.route("/release-products", methods=["GET"])
def list_release_products():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    status = request.args.get("status")
    return list_response(db.release_products, lambda e: status is None or e["status"] == status)


@app.route("/release-products/<rid>/release", methods=["POST"])
def release_release_product(rid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    rp = services.find_or_404(db.release_products, rid)
    if rp["status"] != "PRE_ORDER_OPEN":
        raise err("ERR_INVALID_STATE", "Release product not in PRE_ORDER_OPEN")
    rp["status"] = "RELEASED"
    touch(rp)
    return response.object_response(serialize(rp))


def _requested_rank(release_product_id, target):
    """created_at_rank for a REQUESTED pre-order on a release: rank 1 = earliest
    by created_at ASC (PRD §3.3). Uses creation sequence, never id."""
    requested = [
        p for p in db.pre_orders.values()
        if p["release_product_id"] == release_product_id and p["status"] == "REQUESTED"
    ]
    requested.sort(key=lambda p: p["_seq"])
    for i, p in enumerate(requested, start=1):
        if p["id"] == target["id"]:
            return i
    return len(requested) + 1


@app.route("/pre-orders", methods=["POST"])
def create_pre_order():
    auth = authenticate()
    require_role(auth, {"Customer"})
    body = get_body()
    require_fields(body, ["customer_id", "release_product_id", "requested_quantity", "deposit_paid_cents"])
    customer_id = require_str(body, "customer_id")
    release_product_id = require_str(body, "release_product_id")
    requested_quantity = require_int(body, "requested_quantity")
    deposit_paid_cents = require_int(body, "deposit_paid_cents")
    require_owner(auth, customer_id)
    cust = services.get_customer(customer_id)
    services.find_or_404(db.release_products, release_product_id)
    if deposit_paid_cents < 0:
        raise err("ERR_INVALID_REQUEST", "deposit_paid_cents must be >= 0")
    # Quantity minimum (priority 7).
    if requested_quantity < 1:
        raise err("ERR_INVALID_QUANTITY", "requested_quantity must be >= 1")
    po = {
        "customer_id": customer_id,
        "release_product_id": release_product_id,
        "requested_quantity": requested_quantity,
        "deposit_paid_cents": deposit_paid_cents,
        "priority_score": 0,
        "status": "REQUESTED",
    }
    stamp_create(po)
    db.pre_orders[po["id"]] = po
    # Deposit ledger row (PRD §3.3): delta = -deposit_paid_cents.
    services.append_ledger(cust, -deposit_paid_cents, "PREORDER_DEPOSIT", source_entity_id=po["id"])
    # Priority score (PRD §3.3).
    rank = _requested_rank(release_product_id, po)
    po["priority_score"] = calc.preorder_priority(cust["loyalty_tier"], deposit_paid_cents, rank)
    touch(po)
    return response.object_response(serialize(po), 201)


@app.route("/pre-orders/<pid>", methods=["GET"])
def get_pre_order(pid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    po = services.find_or_404(db.pre_orders, pid)
    require_owner(auth, po["customer_id"])
    return response.object_response(serialize(po))


@app.route("/pre-orders", methods=["GET"])
def list_pre_orders():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    customer_id = request.args.get("customer_id")
    release_product_id = request.args.get("release_product_id")
    status = request.args.get("status")
    if auth.role == "Customer":
        customer_id = auth.user_id

    def pred(p):
        if customer_id is not None and p["customer_id"] != customer_id:
            return False
        if release_product_id is not None and p["release_product_id"] != release_product_id:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    return list_response(db.pre_orders, pred)


@app.route("/pre-orders/<pid>/allocate", methods=["POST"])
def allocate_pre_order(pid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    po = services.find_or_404(db.pre_orders, pid)
    body = get_body()
    rp = db.release_products[po["release_product_id"]]
    # State (priority 4): allocate defined only from REQUESTED, parent must be
    # PRE_ORDER_OPEN.
    if po["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Pre-order not in REQUESTED")
    if rp["status"] != "PRE_ORDER_OPEN":
        raise err("ERR_INVALID_STATE", "Release product not in PRE_ORDER_OPEN")
    # Request well-formedness (priority 6): expected_release_product_version is
    # required.
    require_fields(body, ["expected_release_product_version"])
    expected = require_int(body, "expected_release_product_version")
    # Allocation overflow (priority 13).
    if rp["quantity_allocated"] + po["requested_quantity"] > rp["allocation_pool"]:
        raise err("ERR_ALLOCATION_EXCEEDED", "Allocation exceeds pool")
    # OCC stale-version (priority 15).
    if expected != rp["version"]:
        raise err("ERR_STALE_VERSION", "Stale release product version")
    po["status"] = "ALLOCATED"
    touch(po)
    rp["quantity_allocated"] += po["requested_quantity"]
    touch(rp)
    return response.object_response(serialize(po))


@app.route("/pre-orders/<pid>/waitlist", methods=["POST"])
def waitlist_pre_order(pid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    po = services.find_or_404(db.pre_orders, pid)
    rp = db.release_products[po["release_product_id"]]
    if po["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Pre-order not in REQUESTED")
    if rp["status"] != "PRE_ORDER_OPEN":
        raise err("ERR_INVALID_STATE", "Release product not in PRE_ORDER_OPEN")
    po["status"] = "WAITLISTED"
    touch(po)
    return response.object_response(serialize(po))


@app.route("/pre-orders/<pid>/fulfill", methods=["POST"])
def fulfill_pre_order(pid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    po = services.find_or_404(db.pre_orders, pid)
    rp = db.release_products[po["release_product_id"]]
    if po["status"] != "ALLOCATED":
        raise err("ERR_INVALID_STATE", "Pre-order not in ALLOCATED")
    if rp["status"] != "RELEASED":
        raise err("ERR_RELEASE_NOT_LIVE", "Release product not RELEASED")
    cust = db.customers[po["customer_id"]]
    remaining = rp["unit_price_cents"] * po["requested_quantity"] - po["deposit_paid_cents"]
    # Insufficient credit (priority 16).
    if cust["store_credit_balance_cents"] < remaining:
        raise err("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit")
    po["status"] = "FULFILLED"
    touch(po)
    services.append_ledger(cust, -remaining, "PREORDER_FULFILL", source_entity_id=po["id"])
    return response.object_response(serialize(po))


@app.route("/pre-orders/<pid>/cancel", methods=["POST"])
def cancel_pre_order(pid):
    auth = authenticate()
    require_role(auth, {"Customer"})
    po = services.find_or_404(db.pre_orders, pid)
    require_owner(auth, po["customer_id"])
    # cancel defined from REQUESTED or ALLOCATED.
    if po["status"] not in ("REQUESTED", "ALLOCATED"):
        raise err("ERR_INVALID_STATE", "Pre-order cannot be cancelled")
    was_allocated = po["status"] == "ALLOCATED"
    po["status"] = "CANCELLED"
    touch(po)
    if was_allocated:
        rp = db.release_products[po["release_product_id"]]
        rp["quantity_allocated"] -= po["requested_quantity"]
        touch(rp)
    return response.object_response(serialize(po))


# ===========================================================================
# Events, registrations, pairings (PRD §3.4, §3.5)
# ===========================================================================

@app.route("/events", methods=["POST"])
def create_event():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["title", "format", "starts_at", "ends_at", "capacity", "entry_fee_cents", "tables_required"])
    title = require_str(body, "title")
    fmt = require_enum(body, "format", EVENT_FORMATS)
    starts_at = parse_datetime(body, "starts_at")
    ends_at = parse_datetime(body, "ends_at")
    capacity = require_int(body, "capacity")
    entry_fee_cents = require_int(body, "entry_fee_cents")
    tables_required = require_int(body, "tables_required")
    if not (ends_at > starts_at):
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    for name, val in [("capacity", capacity), ("entry_fee_cents", entry_fee_cents), ("tables_required", tables_required)]:
        if val < 0:
            raise err("ERR_INVALID_REQUEST", f"{name} must be >= 0")
    ev = {
        "title": title,
        "format": fmt,
        "starts_at": db.iso(starts_at),
        "ends_at": db.iso(ends_at),
        "capacity": capacity,
        "entry_fee_cents": entry_fee_cents,
        "tables_required": tables_required,
        "seated_count": 0,
        "current_round": 0,
        "status": "SCHEDULED",
    }
    stamp_create(ev)
    db.events[ev["id"]] = ev
    return response.object_response(serialize(ev), 201)


@app.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    ev = services.find_or_404(db.events, eid)
    return response.object_response(serialize(ev))


@app.route("/events", methods=["GET"])
def list_events():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    status = request.args.get("status")
    fmt = request.args.get("format")

    def pred(e):
        if status is not None and e["status"] != status:
            return False
        if fmt is not None and e["format"] != fmt:
            return False
        return True

    return list_response(db.events, pred)


@app.route("/events/<eid>/registrations", methods=["GET"])
def list_event_registrations(eid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    services.find_or_404(db.events, eid)
    return list_response(db.registrations, lambda r: r["event_id"] == eid)


@app.route("/events/<eid>/pairings", methods=["GET"])
def list_event_pairings(eid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    services.find_or_404(db.events, eid)
    round_number = request.args.get("round_number")

    def pred(p):
        if p["event_id"] != eid:
            return False
        if round_number is not None:
            try:
                if p["round_number"] != int(round_number):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    return list_response(db.pairings, pred)


@app.route("/events/<eid>/wpn-report", methods=["GET"])
def wpn_report(eid):
    auth = authenticate()
    require_role(auth, {"StoreManager", "JudgeStaff"})
    ev = services.find_or_404(db.events, eid)
    # Standings ordered by match_points DESC, ties by created_at ASC (PRD §3.5).
    regs = [r for r in db.registrations.values() if r["event_id"] == eid]
    regs.sort(key=lambda r: (-r["match_points"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(regs)
    page = regs[offset:offset + limit]
    return response.array_response([public(r) for r in page], limit, offset, total)


def _padded_window(ev):
    """[starts_at - BUFFER, ends_at + BUFFER) for venue-overlap check."""
    from common import _parse_iso
    from datetime import timedelta
    start = _parse_iso(ev["starts_at"]) - timedelta(minutes=BUFFER_MINUTES)
    end = _parse_iso(ev["ends_at"]) + timedelta(minutes=BUFFER_MINUTES)
    return start, end


@app.route("/events/<eid>/open", methods=["POST"])
def open_event(eid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    ev = services.find_or_404(db.events, eid)
    # State (priority 4): open defined only from SCHEDULED.
    if ev["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Event not in SCHEDULED")
    # Capacity >= 1 (ERR_INVALID_EVENT_CAPACITY).
    if ev["capacity"] < 1:
        raise err("ERR_INVALID_EVENT_CAPACITY", "Event capacity must be >= 1")
    # Venue overlap (priority 10): padded windows; concurrent tables_required of
    # overlapping non-terminal events + this event must not exceed
    # STORE_TABLE_COUNT.
    my_start, my_end = _padded_window(ev)
    for other in db.events.values():
        if other["id"] == ev["id"]:
            continue
        if other["status"] in ("COMPLETE", "CANCELLED", "SCHEDULED"):
            continue
        o_start, o_end = _padded_window(other)
        # half-open overlap on padded windows
        if my_start < o_end and o_start < my_end:
            if ev["tables_required"] + other["tables_required"] > STORE_TABLE_COUNT:
                raise err("ERR_VENUE_OVERLAP", "Venue table overlap")
    ev["status"] = "OPEN"
    touch(ev)
    return response.object_response(serialize(ev))


@app.route("/events/<eid>/start", methods=["POST"])
def start_event(eid):
    auth = authenticate()
    require_role(auth, {"JudgeStaff"})
    ev = services.find_or_404(db.events, eid)
    if ev["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Event not in OPEN")
    if ev["seated_count"] < 1:
        raise err("ERR_NO_SEATED_PLAYERS", "No seated players")
    ev["status"] = "IN_PROGRESS"
    ev["current_round"] = 1
    touch(ev)
    return response.object_response(serialize(ev))


def _round_complete(eid, round_number):
    pairings = [p for p in db.pairings.values() if p["event_id"] == eid and p["round_number"] == round_number]
    return all(p["result"] != "PENDING" for p in pairings)


@app.route("/events/<eid>/advance-round", methods=["POST"])
def advance_round(eid):
    auth = authenticate()
    require_role(auth, {"JudgeStaff"})
    ev = services.find_or_404(db.events, eid)
    if ev["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Event not in IN_PROGRESS")
    if not _round_complete(eid, ev["current_round"]):
        raise err("ERR_ROUND_NOT_COMPLETE", "Current round not complete")
    if ev["current_round"] >= MAX_ROUNDS:
        raise err("ERR_MAX_ROUNDS_REACHED", "Max rounds reached")
    ev["current_round"] += 1
    touch(ev)
    return response.object_response(serialize(ev))


@app.route("/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    auth = authenticate()
    require_role(auth, {"JudgeStaff"})
    ev = services.find_or_404(db.events, eid)
    if ev["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Event not in IN_PROGRESS")
    if not _round_complete(eid, ev["current_round"]):
        raise err("ERR_ROUND_NOT_COMPLETE", "Current round not complete")
    ev["status"] = "COMPLETE"
    touch(ev)
    return response.object_response(serialize(ev))


def _refund_registration(reg):
    """Drive PAID -> REFUNDED: append EVENT_REFUND ledger row (PRD §3.4)."""
    refund = reg["charged_fee_cents"] if reg["checkin_status"] == "CHECKED_IN" else reg["quoted_fee_cents"]
    reg["payment_status"] = "REFUNDED"
    touch(reg)
    cust = db.customers[reg["customer_id"]]
    services.append_ledger(cust, refund, "EVENT_REFUND", source_entity_id=reg["id"])


@app.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    ev = services.find_or_404(db.events, eid)
    # cancel available from SCHEDULED or OPEN.
    if ev["status"] not in ("SCHEDULED", "OPEN"):
        raise err("ERR_INVALID_STATE", "Event cannot be cancelled")
    ev["status"] = "CANCELLED"
    touch(ev)
    # Cascade: every non-WITHDRAWN registration -> WITHDRAWN; PAID -> REFUNDED.
    regs = [r for r in db.registrations.values() if r["event_id"] == eid]
    regs.sort(key=lambda r: r["_seq"])
    for reg in regs:
        if reg["checkin_status"] == "WITHDRAWN":
            continue
        was_paid = reg["payment_status"] == "PAID"
        reg["checkin_status"] = "WITHDRAWN"
        touch(reg)
        if was_paid:
            _refund_registration(reg)
    return response.object_response(serialize(ev))


def _is_early(ev):
    from common import _parse_iso
    from datetime import timedelta
    starts_at = _parse_iso(ev["starts_at"])
    return db.get_clock() <= starts_at - timedelta(seconds=calc.EARLY_BIRD_LEAD_SECONDS)


@app.route("/registrations", methods=["POST"])
def create_registration():
    auth = authenticate()
    require_role(auth, {"Customer"})
    body = get_body()
    require_fields(body, ["event_id", "customer_id"])
    event_id = require_str(body, "event_id")
    customer_id = require_str(body, "customer_id")
    require_owner(auth, customer_id)
    # Existence (priority 3): validate FKs left to right.
    ev = services.find_or_404(db.events, event_id)
    cust = services.get_customer(customer_id)
    # Banned customers cannot register (PRD §3.1).
    if cust["status"] == "BANNED":
        raise err("ERR_CUSTOMER_BANNED", "Customer is banned")
    # Schedule conflict (priority 9): half-open [starts_at, ends_at) overlap
    # across the customer's non-WITHDRAWN registrations.
    from common import _parse_iso
    new_start = _parse_iso(ev["starts_at"])
    new_end = _parse_iso(ev["ends_at"])
    for r in db.registrations.values():
        if r["customer_id"] != customer_id or r["checkin_status"] == "WITHDRAWN":
            continue
        other_ev = db.events.get(r["event_id"])
        if other_ev is None:
            continue
        o_start = _parse_iso(other_ev["starts_at"])
        o_end = _parse_iso(other_ev["ends_at"])
        if new_start < o_end and o_start < new_end:
            raise err("ERR_SCHEDULE_CONFLICT", "Overlapping registration")
    # Event full (priority 14): seated/registered count must not exceed capacity.
    active = [
        r for r in db.registrations.values()
        if r["event_id"] == event_id and r["checkin_status"] != "WITHDRAWN"
    ]
    if len(active) + 1 > ev["capacity"]:
        raise err("ERR_EVENT_FULL", "Event is full")
    reg = {
        "event_id": event_id,
        "customer_id": customer_id,
        "payment_status": "UNPAID",
        "checkin_status": "PENDING",
        "quoted_fee_cents": calc.registration_fee_provisional(ev["entry_fee_cents"], cust["loyalty_tier"]),
        "charged_fee_cents": 0,
        "match_points": 0,
    }
    stamp_create(reg)
    db.registrations[reg["id"]] = reg
    return response.object_response(serialize(reg), 201)


@app.route("/registrations/<rid>", methods=["GET"])
def get_registration(rid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    reg = services.find_or_404(db.registrations, rid)
    require_owner(auth, reg["customer_id"])
    return response.object_response(serialize(reg))


@app.route("/registrations/<rid>/pay", methods=["POST"])
def pay_registration(rid):
    auth = authenticate()
    require_role(auth, {"Customer"})
    reg = services.find_or_404(db.registrations, rid)
    require_owner(auth, reg["customer_id"])
    # State (priority 4): pay defined from UNPAID; rejected if WITHDRAWN.
    if reg["checkin_status"] == "WITHDRAWN":
        raise err("ERR_INVALID_STATE", "Registration withdrawn")
    if reg["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "Registration not UNPAID")
    cust = db.customers[reg["customer_id"]]
    # Insufficient credit (priority 16).
    if cust["store_credit_balance_cents"] < reg["quoted_fee_cents"]:
        raise err("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit")
    reg["payment_status"] = "PAID"
    touch(reg)
    services.append_ledger(cust, -reg["quoted_fee_cents"], "EVENT_CHARGE", source_entity_id=reg["id"])
    return response.object_response(serialize(reg))


@app.route("/registrations/<rid>/check-in", methods=["POST"])
def check_in_registration(rid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    reg = services.find_or_404(db.registrations, rid)
    ev = db.events[reg["event_id"]]
    cust = db.customers[reg["customer_id"]]
    # State (priority 4): check-in defined from PENDING.
    if reg["checkin_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Registration not PENDING check-in")
    # payment must be PAID (ERR_REGISTRATION_NOT_PAID).
    if reg["payment_status"] != "PAID":
        raise err("ERR_REGISTRATION_NOT_PAID", "Registration not paid")
    # banned check (priority 5, part of state stage).
    if cust["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_BANNED", "Customer is banned")
    # parent event OPEN or IN_PROGRESS.
    if ev["status"] not in ("OPEN", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Event not OPEN/IN_PROGRESS")
    reg["checkin_status"] = "CHECKED_IN"
    reg["charged_fee_cents"] = calc.registration_fee_final(
        ev["entry_fee_cents"], cust["loyalty_tier"], _is_early(ev)
    )
    touch(reg)
    ev["seated_count"] += 1
    touch(ev)
    return response.object_response(serialize(reg))


@app.route("/registrations/<rid>/withdraw", methods=["POST"])
def withdraw_registration(rid):
    auth = authenticate()
    require_role(auth, {"Customer"})
    reg = services.find_or_404(db.registrations, rid)
    require_owner(auth, reg["customer_id"])
    ev = db.events[reg["event_id"]]
    # withdraw defined from PENDING check-in; not while event COMPLETE.
    if reg["checkin_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Registration not PENDING")
    if ev["status"] == "COMPLETE":
        raise err("ERR_INVALID_STATE", "Event is complete")
    was_paid = reg["payment_status"] == "PAID"
    reg["checkin_status"] = "WITHDRAWN"
    touch(reg)
    if was_paid:
        _refund_registration(reg)
    return response.object_response(serialize(reg))


@app.route("/pairings", methods=["POST"])
def create_pairing():
    auth = authenticate()
    require_role(auth, {"JudgeStaff"})
    body = get_body()
    require_fields(body, ["event_id", "registration_a_id"])
    event_id = require_str(body, "event_id")
    registration_a_id = require_str(body, "registration_a_id")
    registration_b_id = body.get("registration_b_id")
    # Existence: event then registration_a then registration_b (if present).
    ev = services.find_or_404(db.events, event_id)
    reg_a = services.find_or_404(db.registrations, registration_a_id)
    if registration_b_id is not None:
        if not isinstance(registration_b_id, str):
            raise err("ERR_INVALID_REQUEST", "registration_b_id must be a string")
        services.find_or_404(db.registrations, registration_b_id)
    # Pairing creation only for an in-progress event's current round.
    if ev["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Event not IN_PROGRESS")
    pairing = {
        "event_id": event_id,
        "round_number": ev["current_round"],
        "registration_a_id": registration_a_id,
        "registration_b_id": registration_b_id,
        "result": "PENDING",
    }
    stamp_create(pairing)
    db.pairings[pairing["id"]] = pairing
    return response.object_response(serialize(pairing), 201)


@app.route("/pairings/<pid>", methods=["GET"])
def get_pairing(pid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    pairing = services.find_or_404(db.pairings, pid)
    return response.object_response(serialize(pairing))


@app.route("/pairings", methods=["GET"])
def list_pairings():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager", "JudgeStaff"})
    event_id = request.args.get("event_id")
    registration_a_id = request.args.get("registration_a_id")
    registration_b_id = request.args.get("registration_b_id")
    round_number = request.args.get("round_number")

    def pred(p):
        if event_id is not None and p["event_id"] != event_id:
            return False
        if registration_a_id is not None and p["registration_a_id"] != registration_a_id:
            return False
        if registration_b_id is not None and p["registration_b_id"] != registration_b_id:
            return False
        if round_number is not None:
            try:
                if p["round_number"] != int(round_number):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    return list_response(db.pairings, pred)


@app.route("/pairings/<pid>/report", methods=["POST"])
def report_pairing(pid):
    auth = authenticate()
    require_role(auth, {"JudgeStaff"})
    pairing = services.find_or_404(db.pairings, pid)
    ev = db.events[pairing["event_id"]]
    # State (priority 4): event must be IN_PROGRESS, pairing PENDING.
    if ev["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Event not IN_PROGRESS")
    if pairing["result"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Pairing already reported")
    body = get_body()
    require_fields(body, ["result"])
    result = require_enum(body, "result", {"A_WINS", "B_WINS", "DRAW", "BYE_A"})
    has_b = pairing["registration_b_id"] is not None
    # Two-player outcomes require b present; BYE_A requires b absent (PRD §3.5).
    if result in ("A_WINS", "B_WINS", "DRAW") and not has_b:
        raise err("ERR_INVALID_STATE", "Two-player result requires second player")
    if result == "BYE_A" and has_b:
        raise err("ERR_INVALID_STATE", "BYE_A requires no second player")
    reg_a = db.registrations[pairing["registration_a_id"]]
    if result == "A_WINS":
        reg_a["match_points"] += 3
        touch(reg_a)
    elif result == "B_WINS":
        reg_b = db.registrations[pairing["registration_b_id"]]
        reg_b["match_points"] += 3
        touch(reg_b)
    elif result == "DRAW":
        reg_b = db.registrations[pairing["registration_b_id"]]
        reg_a["match_points"] += 1
        touch(reg_a)
        reg_b["match_points"] += 1
        touch(reg_b)
    elif result == "BYE_A":
        reg_a["match_points"] += 3
        touch(reg_a)
    pairing["result"] = result
    touch(pairing)
    return response.object_response(serialize(pairing))


# ===========================================================================
# Grading submissions (PRD §3.6)
# ===========================================================================

@app.route("/grading-submissions", methods=["POST"])
def create_grading_submission():
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    body = get_body()
    require_fields(body, ["customer_id", "inventory_item_id", "declared_value_cents", "service_tier"])
    customer_id = require_str(body, "customer_id")
    inventory_item_id = require_str(body, "inventory_item_id")
    declared_value_cents = require_int(body, "declared_value_cents")
    service_tier = require_enum(body, "service_tier", SERVICE_TIERS)
    services.get_customer(customer_id)
    services.get_inventory_item(inventory_item_id)
    if declared_value_cents < 0:
        raise err("ERR_INVALID_REQUEST", "declared_value_cents must be >= 0")
    gs = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "declared_value_cents": declared_value_cents,
        "service_tier": service_tier,
        "grading_fee_cents": 0,
        "assigned_grade": None,
        "status": "INTAKE",
    }
    stamp_create(gs)
    db.grading_submissions[gs["id"]] = gs
    return response.object_response(serialize(gs), 201)


@app.route("/grading-submissions/<gid>", methods=["GET"])
def get_grading_submission(gid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    gs = services.find_or_404(db.grading_submissions, gid)
    require_owner(auth, gs["customer_id"])
    return response.object_response(serialize(gs))


@app.route("/grading-submissions", methods=["GET"])
def list_grading_submissions():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    customer_id = request.args.get("customer_id")
    inventory_item_id = request.args.get("inventory_item_id")
    status = request.args.get("status")
    if auth.role == "Customer":
        customer_id = auth.user_id

    def pred(g):
        if customer_id is not None and g["customer_id"] != customer_id:
            return False
        if inventory_item_id is not None and g["inventory_item_id"] != inventory_item_id:
            return False
        if status is not None and g["status"] != status:
            return False
        return True

    return list_response(db.grading_submissions, pred)


@app.route("/grading-submissions/<gid>/send", methods=["POST"])
def send_grading_submission(gid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    gs = services.find_or_404(db.grading_submissions, gid)
    if gs["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Grading submission not in INTAKE")
    item = db.inventory_items[gs["inventory_item_id"]]
    # Reserved-inventory protection (priority 12).
    if item["quantity_on_hand"] - 1 < item["quantity_reserved"]:
        raise err("ERR_INVENTORY_RESERVED", "Holding one unit over-commits inventory")
    gs["grading_fee_cents"] = calc.grading_fee(gs["declared_value_cents"], gs["service_tier"])
    gs["status"] = "AT_GRADER"
    touch(gs)
    item["quantity_reserved"] += 1
    touch(item)
    return response.object_response(serialize(gs))


@app.route("/grading-submissions/<gid>/return-result", methods=["POST"])
def return_grading_result(gid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    gs = services.find_or_404(db.grading_submissions, gid)
    if gs["status"] != "AT_GRADER":
        raise err("ERR_INVALID_STATE", "Grading submission not AT_GRADER")
    body = get_body()
    # Fork on whether assigned_grade is supplied (PRD §3.6).
    if "assigned_grade" in body and body["assigned_grade"] is not None:
        grade = body["assigned_grade"]
        if isinstance(grade, bool) or not isinstance(grade, (int, float)):
            raise err("ERR_INVALID_GRADE", "assigned_grade must be numeric")
        if not (1 <= grade <= 10):
            raise err("ERR_INVALID_GRADE", "assigned_grade must be in [1,10]")
        gs["assigned_grade"] = grade
        gs["status"] = "GRADED"
    else:
        gs["assigned_grade"] = None
        gs["status"] = "REJECTED"
    touch(gs)
    return response.object_response(serialize(gs))


@app.route("/grading-submissions/<gid>/release", methods=["POST"])
def release_grading_submission(gid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    gs = services.find_or_404(db.grading_submissions, gid)
    if gs["status"] not in ("GRADED", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Grading submission not GRADED/REJECTED")
    gs["status"] = "RETURNED"
    touch(gs)
    item = db.inventory_items[gs["inventory_item_id"]]
    item["quantity_reserved"] -= 1
    touch(item)
    return response.object_response(serialize(gs))


# ===========================================================================
# Consignment cases (PRD §3.7)
# ===========================================================================

@app.route("/consignment-cases", methods=["POST"])
def create_consignment_case():
    auth = authenticate()
    require_role(auth, {"Customer"})
    body = get_body()
    require_fields(body, ["customer_id", "inventory_item_id", "quantity", "ask_price_cents", "commission_rate_bps"])
    customer_id = require_str(body, "customer_id")
    inventory_item_id = require_str(body, "inventory_item_id")
    quantity = require_int(body, "quantity")
    ask_price_cents = require_int(body, "ask_price_cents")
    commission_rate_bps = require_int(body, "commission_rate_bps")
    require_owner(auth, customer_id)
    services.get_customer(customer_id)
    services.get_inventory_item(inventory_item_id)
    if ask_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "ask_price_cents must be >= 0")
    if not (0 <= commission_rate_bps <= 10000):
        raise err("ERR_INVALID_REQUEST", "commission_rate_bps must be in [0,10000]")
    # Quantity minimum (priority 7).
    if quantity < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1")
    case = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
        "ask_price_cents": ask_price_cents,
        "commission_rate_bps": commission_rate_bps,
        "payout_total_cents": 0,
        "status": "LISTED",
    }
    stamp_create(case)
    db.consignment_cases[case["id"]] = case
    return response.object_response(serialize(case), 201)


@app.route("/consignment-cases/<cid>", methods=["GET"])
def get_consignment_case(cid):
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    case = services.find_or_404(db.consignment_cases, cid)
    require_owner(auth, case["customer_id"])
    return response.object_response(serialize(case))


@app.route("/consignment-cases", methods=["GET"])
def list_consignment_cases():
    auth = authenticate()
    require_role(auth, {"Customer", "StoreManager"})
    customer_id = request.args.get("customer_id")
    inventory_item_id = request.args.get("inventory_item_id")
    status = request.args.get("status")
    if auth.role == "Customer":
        customer_id = auth.user_id

    def pred(c):
        if customer_id is not None and c["customer_id"] != customer_id:
            return False
        if inventory_item_id is not None and c["inventory_item_id"] != inventory_item_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    return list_response(db.consignment_cases, pred)


@app.route("/consignment-cases/<cid>/sell", methods=["POST"])
def sell_consignment_case(cid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    case = services.find_or_404(db.consignment_cases, cid)
    if case["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Case not LISTED")
    case["payout_total_cents"] = calc.consignment_payout(
        case["ask_price_cents"], case["commission_rate_bps"], case["quantity"]
    )
    case["status"] = "SOLD"
    touch(case)
    return response.object_response(serialize(case))


@app.route("/consignment-cases/<cid>/settle", methods=["POST"])
def settle_consignment_case(cid):
    auth = authenticate()
    require_role(auth, {"StoreManager"})
    case = services.find_or_404(db.consignment_cases, cid)
    if case["status"] != "SOLD":
        raise err("ERR_INVALID_STATE", "Case not SOLD")
    case["status"] = "SETTLED"
    touch(case)
    cust = db.customers[case["customer_id"]]
    services.append_ledger(cust, case["payout_total_cents"], "CONSIGNMENT_PAYOUT", source_entity_id=case["id"])
    return response.object_response(serialize(case))


@app.route("/consignment-cases/<cid>/withdraw", methods=["POST"])
def withdraw_consignment_case(cid):
    auth = authenticate()
    require_role(auth, {"Customer"})
    case = services.find_or_404(db.consignment_cases, cid)
    require_owner(auth, case["customer_id"])
    if case["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Case not LISTED")
    case["status"] = "WITHDRAWN"
    touch(case)
    return response.object_response(serialize(case))


def _serve(host, port):
    """Serve via Werkzeug's make_server with a short bind-retry loop.

    Under per-test-server isolation the runner kills the previous server and
    immediately spawns a new one before every test. When many rounds run
    concurrently, the just-killed listener's port can still be briefly held by
    the OS (or by a not-yet-reaped sibling), so a one-shot bind would crash with
    EADDRINUSE and the runner would report "could not be restarted". Retrying the
    bind for a few seconds lets the new server reliably claim the port once the
    old one releases it. SO_REUSEADDR (Werkzeug's default) makes this fast.
    """
    import time
    from werkzeug.serving import make_server

    deadline = time.time() + 20.0
    last_err = None
    while time.time() < deadline:
        try:
            srv = make_server(host, port, app, threaded=True)
            break
        except OSError as e:  # EADDRINUSE / EACCES race during rebind
            last_err = e
            time.sleep(0.25)
    else:
        raise last_err
    srv.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve("0.0.0.0", port)
