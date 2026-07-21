"""Spice, Tea & Bulk-Herb Shop API — Flask entry point and routes."""
import os
from flask import Flask, request

import store as db
from store import (parse_dt, clock_now, touch, new_common, gen_id, now_iso,
                   fmt_dt, rhu_cents, rhu_rate)
from envelope import ApiError, ok, ok_list, err
from auth import (identity, require_roles, get_body, paginate,
                  req_str, req_int, req_num, req_enum, opt_enum, opt_bool, opt_int)
import services as svc

app = Flask(__name__)

CLEANING_BUFFER_MIN = 30
CATEGORY_CHOICES = {"SPICE", "TEA", "HERB"}
KIND_CHOICES = {"SIMPLE", "BLEND"}
TIER_CHOICES = {"BRONZE", "SILVER", "GOLD"}


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return err("ERR_VALIDATION", 400, "Unknown route")


@app.errorhandler(405)
def _handle_405(e):
    return err("ERR_VALIDATION", 400, "Method not allowed")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err(e.error_id, e.http_status, e.message)
    return err("ERR_VALIDATION", 400, f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Existence lookups (each raises its dedicated 404)
# ---------------------------------------------------------------------------
def get_product(pid):
    p = db.products.get(pid)
    if p is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404)
    return p


def get_lot(lid):
    l = db.inventory_lots.get(lid)
    if l is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404)
    return l


def get_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404)
    return b


def get_line(lid):
    l = db.order_lines.get(lid)
    if l is None:
        raise ApiError("ERR_LINE_NOT_FOUND", 404)
    return l


def get_order(oid):
    o = db.customer_orders.get(oid)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404)
    return o


def get_account(aid):
    a = db.wholesale_accounts.get(aid)
    if a is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404)
    return a


def get_production_line(plid):
    pl = db.production_lines.get(plid)
    if pl is None:
        raise ApiError("ERR_LINE_RESOURCE_NOT_FOUND", 404)
    return pl


def get_station(sid):
    s = db.labeling_stations.get(sid)
    if s is None:
        raise ApiError("ERR_STATION_NOT_FOUND", 404)
    return s


def get_tin_run(tid):
    t = db.tin_runs.get(tid)
    if t is None:
        raise ApiError("ERR_TIN_RUN_NOT_FOUND", 404)
    return t


def get_component(cid):
    c = db.blend_components.get(cid)
    if c is None:
        raise ApiError("ERR_COMPONENT_NOT_FOUND", 404)
    return c


def _sorted(records):
    return sorted(records, key=lambda r: r["_seq"])


# ===========================================================================
# Product
# ===========================================================================
@app.post("/products")
def create_product():
    _, role = identity()
    require_roles(role, {"CatalogManager"})
    body = get_body()
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORY_CHOICES)
    kind = req_enum(body, "kind", KIND_CHOICES)
    unit_price = req_num(body, "unit_price_cents_per_gram", exclusive_min=0)
    tare = req_int(body, "tare_default_grams", minimum=0)
    shelf_life = opt_int(body, "shelf_life_days", 365, minimum=0)
    allergen_tags = body.get("allergen_tags")
    if allergen_tags is None:
        allergen_tags = []
    if not isinstance(allergen_tags, list) or not all(isinstance(x, str) for x in allergen_tags):
        raise ApiError("ERR_VALIDATION", 400, "allergen_tags must be an array of strings")
    if kind == "BLEND":
        allergen_tags = []  # ignored for blends (PRD 3.1)

    p = new_common()
    p.update({
        "name": name, "category": category, "kind": kind,
        "unit_price_cents_per_gram": unit_price,
        "tare_default_grams": tare,
        "allergen_tags": allergen_tags,
        "shelf_life_days": shelf_life,
        "status": "ACTIVE",
        "stock_state": "OUT_OF_STOCK",
    })
    db.products[p["id"]] = p
    return ok(svc.ser_product(p), 201)


@app.get("/products/<pid>")
def fetch_product(pid):
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent",
                         "Wholesaler"})
    p = get_product(pid)
    return ok(svc.ser_product(p))


@app.get("/products")
def list_products():
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent",
                         "Wholesaler"})
    items = _sorted(db.products.values())
    status_f = request.args.get("status")
    category_f = request.args.get("category")
    kind_f = request.args.get("kind")
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    if category_f is not None:
        items = [p for p in items if p["category"] == category_f]
    if kind_f is not None:
        items = [p for p in items if p["kind"] == kind_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_product(p) for p in page], limit, offset, total)


@app.post("/products/<pid>/discontinue")
def discontinue_product(pid):
    _, role = identity()
    require_roles(role, {"CatalogManager"})
    p = get_product(pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    p["status"] = "DISCONTINUED"
    touch(p)
    return ok(svc.ser_product(p))


# ===========================================================================
# BlendComponent
# ===========================================================================
@app.post("/blend-components")
def create_blend_component():
    _, role = identity()
    require_roles(role, {"CatalogManager"})
    body = get_body()
    blend_pid = req_str(body, "blend_product_id")
    comp_pid = req_str(body, "component_product_id")
    ratio = req_int(body, "weight_ratio_bps")
    # Existence: product family, left-to-right (blend then component)
    get_product(blend_pid)
    get_product(comp_pid)
    if ratio < 1 or ratio > 10000:
        raise ApiError("ERR_VALIDATION", 400, "weight_ratio_bps must be 1..10000")
    # Duplicate component check
    for c in db.blend_components.values():
        if c["blend_product_id"] == blend_pid and c["component_product_id"] == comp_pid:
            raise ApiError("ERR_DUPLICATE_COMPONENT", 409)
    c = {"id": gen_id(), "created_at": now_iso(), "_seq": db.next_seq(),
         "blend_product_id": blend_pid, "component_product_id": comp_pid,
         "weight_ratio_bps": ratio}
    db.blend_components[c["id"]] = c
    return ok(svc.ser_blend_component(c), 201)


@app.get("/blend-components/<cid>")
def fetch_blend_component(cid):
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent"})
    c = get_component(cid)
    return ok(svc.ser_blend_component(c))


@app.get("/blend-components")
def list_blend_components():
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent"})
    items = _sorted(db.blend_components.values())
    blend_f = request.args.get("blend_product_id")
    comp_f = request.args.get("component_product_id")
    if blend_f is not None:
        items = [c for c in items if c["blend_product_id"] == blend_f]
    if comp_f is not None:
        items = [c for c in items if c["component_product_id"] == comp_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_blend_component(c) for c in page], limit, offset, total)


# ===========================================================================
# InventoryLot
# ===========================================================================
@app.post("/inventory-lots")
def create_inventory_lot():
    _, role = identity()
    require_roles(role, {"CatalogManager"})
    body = get_body()
    product_id = req_str(body, "product_id")
    lot_code = req_str(body, "lot_code")
    grams_received = req_int(body, "grams_received", exclusive_min=0)
    received_at = req_str(body, "received_at")
    best_by = req_str(body, "best_by")
    get_product(product_id)
    rec_dt = parse_dt(received_at)
    bb_dt = parse_dt(best_by)
    if rec_dt is None or bb_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "received_at/best_by must be ISO 8601 datetimes")
    lot = new_common()
    lot.update({
        "product_id": product_id,
        "source_batch_id": None,
        "lot_code": lot_code,
        "grams_received": grams_received,
        "grams_on_hand": grams_received,
        "received_at": received_at,
        "best_by": best_by,
        "_received_at_dt": rec_dt,
        "_best_by_dt": bb_dt,
    })
    db.inventory_lots[lot["id"]] = lot
    svc.reconcile_stock(product_id)
    return ok(svc.ser_lot(lot), 201)


@app.get("/inventory-lots/<lid>")
def fetch_inventory_lot(lid):
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent"})
    lot = get_lot(lid)
    return ok(svc.ser_lot(lot))


@app.get("/inventory-lots")
def list_inventory_lots():
    _, role = identity()
    require_roles(role, {"CatalogManager", "ProductionOperator", "SalesAgent"})
    items = _sorted(db.inventory_lots.values())
    product_f = request.args.get("product_id")
    batch_f = request.args.get("source_batch_id")
    status_f = request.args.get("status")
    if product_f is not None:
        items = [l for l in items if l["product_id"] == product_f]
    if batch_f is not None:
        items = [l for l in items if l["source_batch_id"] == batch_f]
    if status_f is not None:
        items = [l for l in items if svc.lot_status(l) == status_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_lot(l) for l in page], limit, offset, total)


# ===========================================================================
# ProductionLine
# ===========================================================================
@app.post("/production-lines")
def create_production_line():
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    body = get_body()
    name = req_str(body, "name")
    pl = new_common()
    pl.update({"name": name})
    db.production_lines[pl["id"]] = pl
    return ok(svc.ser_production_line(pl), 201)


@app.get("/production-lines/<plid>")
def fetch_production_line(plid):
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager", "SalesAgent"})
    pl = get_production_line(plid)
    return ok(svc.ser_production_line(pl))


# ===========================================================================
# Batch
# ===========================================================================
def _windows_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@app.post("/batches")
def create_batch():
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    body = get_body()
    blend_pid = req_str(body, "blend_product_id")
    line_id = req_str(body, "production_line_id")
    target = req_int(body, "target_output_grams", exclusive_min=0)
    start_s = req_str(body, "scheduled_start")
    end_s = req_str(body, "scheduled_end")
    get_product(blend_pid)
    get_production_line(line_id)
    start_dt = parse_dt(start_s)
    end_dt = parse_dt(end_s)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_start/scheduled_end must be ISO 8601")
    if start_dt >= end_dt:
        raise ApiError("ERR_WINDOW_INVALID", 409)
    for b in db.batches.values():
        if b["production_line_id"] == line_id:
            if _windows_overlap(start_dt, end_dt, b["_start_dt"], b["_end_dt"]):
                raise ApiError("ERR_LINE_WINDOW_CONFLICT", 409)
    b = new_common()
    b.update({
        "blend_product_id": blend_pid,
        "production_line_id": line_id,
        "target_output_grams": target,
        "produced_grams": 0,
        "scheduled_start": start_s,
        "scheduled_end": end_s,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "status": "PLANNED",
    })
    db.batches[b["id"]] = b
    return ok(svc.ser_batch(b), 201)


@app.get("/batches/<bid>")
def fetch_batch(bid):
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager"})
    b = get_batch(bid)
    return ok(svc.ser_batch(b))


@app.get("/batches")
def list_batches():
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager"})
    items = _sorted(db.batches.values())
    blend_f = request.args.get("blend_product_id")
    line_f = request.args.get("production_line_id")
    status_f = request.args.get("status")
    if blend_f is not None:
        items = [b for b in items if b["blend_product_id"] == blend_f]
    if line_f is not None:
        items = [b for b in items if b["production_line_id"] == line_f]
    if status_f is not None:
        items = [b for b in items if b["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_batch(b) for b in page], limit, offset, total)


def _fefo_sorted(lots):
    return sorted(lots, key=lambda l: (l["_best_by_dt"], l["_received_at_dt"], l["_seq"]))


@app.post("/batches/<bid>/produce")
def produce_batch(bid):
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    b = get_batch(bid)
    if b["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    blend = db.products.get(b["blend_product_id"])
    if blend is None or blend["kind"] != "BLEND":
        raise ApiError("ERR_PRODUCT_NOT_BLEND", 422)
    components = [c for c in db.blend_components.values()
                 if c["blend_product_id"] == blend["id"]]
    total_bps = sum(c["weight_ratio_bps"] for c in components)
    if total_bps != 10000:
        raise ApiError("ERR_INVALID_RATIO", 422)

    target = b["target_output_grams"]
    # Plan draws for every component atomically (check all before committing).
    plan = []  # list of (lot, grams_to_draw)
    for comp in components:
        need = -(-(target * comp["weight_ratio_bps"]) // 10000)  # ceil division
        lots = [l for l in db.inventory_lots.values()
                if l["product_id"] == comp["component_product_id"]
                and svc.lot_status(l) == "AVAILABLE"]
        available = sum(l["grams_on_hand"] for l in lots)
        if available < need:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409)
        remaining = need
        for lot in _fefo_sorted(lots):
            if remaining <= 0:
                break
            take = min(remaining, lot["grams_on_hand"])
            if take > 0:
                plan.append((lot, take))
                remaining -= take

    # Commit draws
    affected_products = set()
    for lot, take in plan:
        lot["grams_on_hand"] -= take
        touch(lot)
        affected_products.add(lot["product_id"])
    for pid in affected_products:
        svc.reconcile_stock(pid)

    # Mint the blend output lot
    clk = clock_now()
    from datetime import timedelta
    bb_dt = clk + timedelta(days=blend["shelf_life_days"])
    lot = new_common()
    lot.update({
        "product_id": blend["id"],
        "source_batch_id": b["id"],
        "lot_code": f"BATCH-{b['id']}",
        "grams_received": target,
        "grams_on_hand": target,
        "received_at": fmt_dt(clk),
        "best_by": fmt_dt(bb_dt),
        "_received_at_dt": clk,
        "_best_by_dt": bb_dt,
    })
    db.inventory_lots[lot["id"]] = lot
    svc.reconcile_stock(blend["id"])

    b["produced_grams"] = target
    b["status"] = "PRODUCED"
    touch(b)
    return ok(svc.ser_batch(b))


# ===========================================================================
# LabelingStation
# ===========================================================================
@app.post("/labeling-stations")
def create_labeling_station():
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    body = get_body()
    name = req_str(body, "name")
    s = new_common()
    s.update({"name": name})
    db.labeling_stations[s["id"]] = s
    return ok(svc.ser_labeling_station(s), 201)


@app.get("/labeling-stations/<sid>")
def fetch_labeling_station(sid):
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager"})
    s = get_station(sid)
    return ok(svc.ser_labeling_station(s))


# ===========================================================================
# TinRun
# ===========================================================================
@app.post("/tin-runs")
def create_tin_run():
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    body = get_body()
    station_id = req_str(body, "labeling_station_id")
    product_ids = body.get("product_ids")
    start_s = req_str(body, "scheduled_start")
    end_s = req_str(body, "scheduled_end")
    if not isinstance(product_ids, list) or not all(isinstance(x, str) for x in product_ids):
        raise ApiError("ERR_VALIDATION", 400, "product_ids must be an array of product ids")
    # Existence: products first (left-to-right), then station (PRD 2.5)
    for pid in product_ids:
        get_product(pid)
    get_station(station_id)
    start_dt = parse_dt(start_s)
    end_dt = parse_dt(end_s)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_start/scheduled_end must be ISO 8601")
    if start_dt >= end_dt:
        raise ApiError("ERR_WINDOW_INVALID", 409)
    from datetime import timedelta
    buffer = timedelta(minutes=CLEANING_BUFFER_MIN)
    for t in db.tin_runs.values():
        if t["labeling_station_id"] == station_id:
            # Conflict if the new run is within the cleaning buffer of an existing run.
            if start_dt < t["_end_dt"] + buffer and t["_start_dt"] < end_dt + buffer:
                raise ApiError("ERR_STATION_BUFFER_CONFLICT", 409)
    allergen_set = set()
    for pid in product_ids:
        allergen_set |= svc.effective_allergens(pid)
    t = new_common()
    t.update({
        "labeling_station_id": station_id,
        "product_ids": list(product_ids),
        "allergen_set": sorted(allergen_set),
        "scheduled_start": start_s,
        "scheduled_end": end_s,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.tin_runs[t["id"]] = t
    return ok(svc.ser_tin_run(t), 201)


@app.get("/tin-runs/<tid>")
def fetch_tin_run(tid):
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager"})
    t = get_tin_run(tid)
    return ok(svc.ser_tin_run(t))


@app.get("/tin-runs")
def list_tin_runs():
    _, role = identity()
    require_roles(role, {"ProductionOperator", "CatalogManager"})
    items = _sorted(db.tin_runs.values())
    station_f = request.args.get("labeling_station_id")
    if station_f is not None:
        items = [t for t in items if t["labeling_station_id"] == station_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_tin_run(t) for t in page], limit, offset, total)


# ===========================================================================
# WholesaleAccount
# ===========================================================================
def _own_account(account_id, uid, role):
    if role == "Wholesaler" and account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403)


@app.post("/wholesale-accounts")
def create_account():
    _, role = identity()
    require_roles(role, {"SalesAgent"})
    body = get_body()
    business_name = req_str(body, "business_name")
    credit_limit = req_int(body, "credit_limit_cents", minimum=0)
    tier = opt_enum(body, "tier", TIER_CHOICES, "BRONZE")
    a = new_common()
    a.update({
        "business_name": business_name,
        "tier": tier,
        "credit_limit_cents": credit_limit,
        "status": "ACTIVE",
    })
    db.wholesale_accounts[a["id"]] = a
    return ok(svc.ser_account(a), 201)


@app.get("/wholesale-accounts/<aid>")
def fetch_account(aid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    _own_account(aid, uid, role)
    a = get_account(aid)
    return ok(svc.ser_account(a))


@app.get("/wholesale-accounts")
def list_accounts():
    _, role = identity()
    require_roles(role, {"SalesAgent"})
    items = _sorted(db.wholesale_accounts.values())
    status_f = request.args.get("status")
    tier_f = request.args.get("tier")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if tier_f is not None:
        items = [a for a in items if a["tier"] == tier_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_account(a) for a in page], limit, offset, total)


@app.post("/wholesale-accounts/<aid>/suspend")
def suspend_account(aid):
    _, role = identity()
    require_roles(role, {"SalesAgent"})
    a = get_account(aid)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    a["status"] = "SUSPENDED"
    touch(a)
    return ok(svc.ser_account(a))


@app.post("/wholesale-accounts/<aid>/reinstate")
def reinstate_account(aid):
    _, role = identity()
    require_roles(role, {"SalesAgent"})
    a = get_account(aid)
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409)
    a["status"] = "ACTIVE"
    touch(a)
    return ok(svc.ser_account(a))


# ===========================================================================
# CustomerOrder
# ===========================================================================
def _own_order(order, uid, role):
    if role == "Wholesaler" and order["wholesale_account_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403)


def _order_lines_of(order_id):
    return _sorted([l for l in db.order_lines.values() if l["order_id"] == order_id])


@app.post("/orders")
def create_order():
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    body = get_body()
    account_id = req_str(body, "wholesale_account_id")
    allergen_ack = opt_bool(body, "allergen_ack", False)
    get_account(account_id)
    _own_account(account_id, uid, role)
    o = new_common()
    o.update({
        "wholesale_account_id": account_id,
        "fulfillment_status": "DRAFT",
        "allergen_ack": allergen_ack,
        "total_net_grams": None,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "held_exposure_cents": 0,
    })
    db.customer_orders[o["id"]] = o
    return ok(svc.ser_order(o), 201)


@app.get("/orders/<oid>")
def fetch_order(oid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler", "ProductionOperator"})
    o = get_order(oid)
    _own_order(o, uid, role)
    return ok(svc.ser_order(o))


@app.get("/orders")
def list_orders():
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler", "ProductionOperator"})
    items = _sorted(db.customer_orders.values())
    if role == "Wholesaler":
        items = [o for o in items if o["wholesale_account_id"] == uid]
    account_f = request.args.get("wholesale_account_id")
    status_f = request.args.get("fulfillment_status")
    if account_f is not None:
        items = [o for o in items if o["wholesale_account_id"] == account_f]
    if status_f is not None:
        items = [o for o in items if o["fulfillment_status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_order(o) for o in page], limit, offset, total)


@app.post("/orders/<oid>/lines")
def add_line(oid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    body = get_body()
    product_id = req_str(body, "product_id")
    requested_grams = req_int(body, "requested_grams", exclusive_min=0)
    # Existence: product then order (PRD 2.5 left-to-right)
    p = get_product(product_id)
    o = get_order(oid)
    _own_order(o, uid, role)
    if o["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_DISCONTINUED", 409)
    line = new_common()
    line.update({
        "order_id": oid,
        "product_id": product_id,
        "requested_grams": requested_grams,
        "gross_grams": None,
        "tare_grams": None,
        "net_grams": None,
        "allocated_lot_id": None,
        "provisional_line_cents": None,
        "final_line_cents": None,
    })
    db.order_lines[line["id"]] = line
    return ok(svc.ser_order_line(line), 201)


def _discount_rate(total_grams):
    if total_grams < 500:
        return "0.00"
    if total_grams < 2000:
        return "0.05"
    return "0.12"


@app.post("/orders/<oid>/price")
def price_order(oid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    o = get_order(oid)
    _own_order(o, uid, role)
    if o["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    lines = _order_lines_of(oid)
    if not lines:
        raise ApiError("ERR_VALIDATION", 400, "Order has no lines")
    for line in lines:
        prod = db.products[line["product_id"]]
        if prod["status"] != "ACTIVE":
            raise ApiError("ERR_PRODUCT_DISCONTINUED", 409)
    subtotal = 0
    total_grams = 0
    for line in lines:
        prod = db.products[line["product_id"]]
        cents = rhu_cents(line["requested_grams"], prod["unit_price_cents_per_gram"])
        line["provisional_line_cents"] = cents
        touch(line)
        subtotal += cents
        total_grams += line["requested_grams"]
    discount = rhu_rate(subtotal, _discount_rate(total_grams))
    o["total_net_grams"] = total_grams
    o["provisional_total_cents"] = subtotal - discount
    o["fulfillment_status"] = "PRICED"
    touch(o)
    return ok(svc.ser_order(o))


@app.post("/orders/<oid>/confirm")
def confirm_order(oid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    body = get_body()
    o = get_order(oid)
    _own_order(o, uid, role)
    if o["fulfillment_status"] != "PRICED":
        raise ApiError("ERR_INVALID_STATE", 409)
    expected = req_int(body, "expected_wholesale_account_version")
    account = db.wholesale_accounts[o["wholesale_account_id"]]
    if expected != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409)
    committed, _ = svc.account_exposures(account["id"])
    available = account["credit_limit_cents"] - committed
    if o["provisional_total_cents"] > available:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402)
    o["held_exposure_cents"] = o["provisional_total_cents"]
    o["fulfillment_status"] = "CONFIRMED"
    touch(o)
    touch(account)  # increments WholesaleAccount.version by 1
    return ok(svc.ser_order(o))


def _measurement_map(body):
    raw = body.get("line_measurements")
    if not isinstance(raw, list):
        raise ApiError("ERR_VALIDATION", 400, "line_measurements must be an array")
    out = {}
    for m in raw:
        if not isinstance(m, dict):
            raise ApiError("ERR_VALIDATION", 400, "each measurement must be an object")
        lid = m.get("order_line_id") or m.get("line_id") or m.get("id")
        if not isinstance(lid, str):
            raise ApiError("ERR_VALIDATION", 400, "measurement missing order_line_id")
        gross = m.get("gross_grams")
        tare = m.get("tare_grams")
        if not (isinstance(gross, int) and not isinstance(gross, bool)):
            raise ApiError("ERR_VALIDATION", 400, "gross_grams must be an integer")
        if not (isinstance(tare, int) and not isinstance(tare, bool)):
            raise ApiError("ERR_VALIDATION", 400, "tare_grams must be an integer")
        net = gross - tare
        if net < 0:
            raise ApiError("ERR_VALIDATION", 400, "net grams cannot be negative")
        out[lid] = (gross, tare, net)
    return out


@app.post("/orders/<oid>/pack")
def pack_order(oid):
    _, role = identity()
    require_roles(role, {"ProductionOperator"})
    body = get_body()
    o = get_order(oid)
    if o["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409)
    lines = _order_lines_of(oid)

    # Allergen acknowledgement gate (priority 6)
    any_allergen = any(svc.effective_allergens(l["product_id"]) for l in lines)
    if any_allergen and not o["allergen_ack"]:
        raise ApiError("ERR_ALLERGEN_LABEL_REQUIRED", 409)

    # Measurements
    meas = _measurement_map(body)
    for line in lines:
        if line["id"] not in meas:
            raise ApiError("ERR_VALIDATION", 400, f"missing measurement for line {line['id']}")

    # FEFO allocation, atomic simulation across lines (priority 7 expired, 9 stock)
    working = {lid: lot["grams_on_hand"] for lid, lot in db.inventory_lots.items()}
    selections = {}       # line_id -> lot_id
    expired_error = False
    stock_error = False
    for line in lines:
        _, _, net = meas[line["id"]]
        prod_id = line["product_id"]
        prod_lots = [lot for lot in db.inventory_lots.values() if lot["product_id"] == prod_id]
        fresh = [lot for lot in prod_lots
                 if svc.lot_status(lot) != "EXPIRED" and working[lot["id"]] >= net]
        if fresh:
            chosen = min(fresh, key=lambda l: (l["_best_by_dt"], l["_received_at_dt"], l["_seq"]))
            selections[line["id"]] = chosen["id"]
            working[chosen["id"]] -= net
        else:
            expired_big = [lot for lot in prod_lots
                           if svc.lot_status(lot) == "EXPIRED" and working[lot["id"]] >= net]
            if expired_big:
                expired_error = True
            else:
                stock_error = True
    if expired_error:
        raise ApiError("ERR_LOT_EXPIRED", 409)
    if stock_error:
        raise ApiError("ERR_INSUFFICIENT_STOCK", 409)

    # Commit: stamp measurements, allocate, decrement lots, cascade stock
    affected_products = set()
    subtotal = 0
    total_grams = 0
    for line in lines:
        gross, tare, net = meas[line["id"]]
        lot = db.inventory_lots[selections[line["id"]]]
        prod = db.products[line["product_id"]]
        line["gross_grams"] = gross
        line["tare_grams"] = tare
        line["net_grams"] = net
        line["allocated_lot_id"] = lot["id"]
        line["final_line_cents"] = rhu_cents(net, prod["unit_price_cents_per_gram"])
        touch(line)
        lot["grams_on_hand"] -= net
        touch(lot)
        affected_products.add(lot["product_id"])
        subtotal += line["final_line_cents"]
        total_grams += net
    for pid in affected_products:
        svc.reconcile_stock(pid)

    discount = rhu_rate(subtotal, _discount_rate(total_grams))
    o["total_net_grams"] = total_grams
    o["final_total_cents"] = subtotal - discount
    o["held_exposure_cents"] = o["final_total_cents"]
    o["fulfillment_status"] = "PACKED"
    touch(o)
    return ok(svc.ser_order(o))


@app.post("/orders/<oid>/ship")
def ship_order(oid):
    _, role = identity()
    require_roles(role, {"SalesAgent"})
    o = get_order(oid)
    if o["fulfillment_status"] != "PACKED":
        raise ApiError("ERR_INVALID_STATE", 409)
    o["fulfillment_status"] = "SHIPPED"
    touch(o)
    return ok(svc.ser_order(o))


@app.post("/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler"})
    o = get_order(oid)
    _own_order(o, uid, role)
    prev = o["fulfillment_status"]
    if prev not in ("DRAFT", "PRICED", "CONFIRMED", "PACKED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    if prev == "PACKED":
        affected = set()
        for line in _order_lines_of(oid):
            if line["allocated_lot_id"] and line["net_grams"]:
                lot = db.inventory_lots.get(line["allocated_lot_id"])
                if lot is not None:
                    lot["grams_on_hand"] += line["net_grams"]
                    touch(lot)
                    affected.add(lot["product_id"])
        for pid in affected:
            svc.reconcile_stock(pid)
    o["held_exposure_cents"] = 0
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    return ok(svc.ser_order(o))


# ===========================================================================
# OrderLine reads
# ===========================================================================
@app.get("/order-lines/<lid>")
def fetch_order_line(lid):
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler", "ProductionOperator"})
    line = get_line(lid)
    if role == "Wholesaler":
        order = db.customer_orders.get(line["order_id"])
        if order is None or order["wholesale_account_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403)
    return ok(svc.ser_order_line(line))


@app.get("/order-lines")
def list_order_lines():
    uid, role = identity()
    require_roles(role, {"SalesAgent", "Wholesaler", "ProductionOperator"})
    items = _sorted(db.order_lines.values())
    if role == "Wholesaler":
        owned = {o["id"] for o in db.customer_orders.values()
                 if o["wholesale_account_id"] == uid}
        items = [l for l in items if l["order_id"] in owned]
    order_f = request.args.get("order_id")
    product_f = request.args.get("product_id")
    lot_f = request.args.get("allocated_lot_id")
    if order_f is not None:
        items = [l for l in items if l["order_id"] == order_f]
    if product_f is not None:
        items = [l for l in items if l["product_id"] == product_f]
    if lot_f is not None:
        items = [l for l in items if l["allocated_lot_id"] == lot_f]
    page, limit, offset, total = paginate(items)
    return ok_list([svc.ser_order_line(l) for l in page], limit, offset, total)


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    _, role = identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 datetime")
    db.clock["now"] = dt
    return ok({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
