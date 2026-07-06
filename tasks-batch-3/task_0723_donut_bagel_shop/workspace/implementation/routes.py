"""All API endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    db, ApiError, ok, ok_list, paginate, sort_by_created,
    get_auth, require_roles, get_or_404, body_json, require_fields, stamp_create, touch,
    parse_iso, CATEGORY_VALUES, ALLERGEN_VALUES, REWARD_VALUE_CENTS,
    CATERING_SLOT_CAPACITY, ROUTE_BUFFER_MINUTES,
)
import calc
import serialize as ser

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _validate_line_items(line_items, allow_marked_down):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "line_items must be a non-empty array")
    for li in line_items:
        if not isinstance(li, dict):
            raise ApiError("ERR_INVALID_REQUEST", 422, "each line item must be an object")
        if li.get("product_id") is None or li.get("qty") is None:
            raise ApiError("ERR_INVALID_REQUEST", 422, "line item requires product_id and qty")
        qty = li["qty"]
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError("ERR_INVALID_REQUEST", 422, "line item qty must be >= 1")
        if not allow_marked_down and li.get("marked_down"):
            raise ApiError("ERR_INVALID_REQUEST", 422, "marked_down not allowed here")


def _check_products_exist(line_items):
    for li in line_items:
        if li["product_id"] not in db.products:
            raise ApiError("ERR_NOT_FOUND", 404, "product not found")


def _require_active_products(line_items):
    for li in line_items:
        p = db.products[li["product_id"]]
        if not p["active"]:
            raise ApiError("ERR_INVALID_REQUEST", 422, "product is retired")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _client_owns(role, uid, account_id):
    if role == "WholesaleClient" and uid != account_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "WholesaleClient may only act on its own account")


# ===========================================================================
# Products
# ===========================================================================
@bp.route("/products", methods=["POST"])
def create_product():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    body = body_json()
    require_fields(body, ["sku", "name", "category", "unit_price_cents",
                          "dozen_price_cents", "bulk_unit_price_cents", "unit_cost_cents"])
    if body["category"] not in CATEGORY_VALUES:
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid category")
    for f in ["unit_price_cents", "dozen_price_cents", "bulk_unit_price_cents"]:
        if not _is_int(body[f]) or body[f] < 1:
            raise ApiError("ERR_INVALID_REQUEST", 422, f"{f} must be integer >= 1")
    if not _is_int(body["unit_cost_cents"]) or body["unit_cost_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "unit_cost_cents must be integer >= 0")
    bulk_threshold = body.get("bulk_threshold", 24)
    if not _is_int(bulk_threshold) or bulk_threshold < 12:
        raise ApiError("ERR_INVALID_REQUEST", 422, "bulk_threshold must be integer >= 12")
    allergens = body.get("allergens", [])
    if not isinstance(allergens, list) or any(a not in ALLERGEN_VALUES for a in allergens):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid allergens")
    if any(p["sku"] == body["sku"] for p in db.products.values()):
        raise ApiError("ERR_INVALID_REQUEST", 422, "sku must be unique")

    rec = {
        "sku": body["sku"], "name": body["name"], "category": body["category"],
        "unit_price_cents": body["unit_price_cents"],
        "dozen_price_cents": body["dozen_price_cents"],
        "bulk_threshold": bulk_threshold,
        "bulk_unit_price_cents": body["bulk_unit_price_cents"],
        "unit_cost_cents": body["unit_cost_cents"],
        "allergens": list(allergens), "active": True,
    }
    stamp_create(rec)
    db.products[rec["id"]] = rec
    return ok(ser.product_out(rec), 201)


@bp.route("/products", methods=["GET"])
def list_products():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager", "RouteDriver", "WholesaleClient"})
    records = list(db.products.values())
    cat = request.args.get("category")
    if cat is not None:
        records = [r for r in records if r["category"] == cat]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.product_out(r) for r in page], limit, offset, total)


@bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager", "RouteDriver", "WholesaleClient"})
    p = get_or_404(db.products, pid)
    return ok(ser.product_out(p))


@bp.route("/products/<pid>/bake-batches", methods=["GET"])
def list_product_batches(pid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "BakeManager"})
    get_or_404(db.products, pid)
    records = [b for b in db.bake_batches.values() if b["product_id"] == pid]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.bake_batch_out(r) for r in page], limit, offset, total)


# ===========================================================================
# Production Days
# ===========================================================================
@bp.route("/production-days", methods=["POST"])
def create_day():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    body = body_json()
    require_fields(body, ["business_date", "delivery_cutoff_utc"])
    try:
        parse_iso(body["delivery_cutoff_utc"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid delivery_cutoff_utc")
    if any(d["business_date"] == body["business_date"] for d in db.production_days.values()):
        raise ApiError("ERR_INVALID_REQUEST", 422, "business_date must be unique")
    rec = {
        "business_date": body["business_date"],
        "delivery_cutoff_utc": body["delivery_cutoff_utc"],
        "status": "OPEN",
        "gross_sales_cents": 0, "markdown_loss_cents": 0, "waste_cost_cents": 0,
        "expected_full_value_cents": 0, "reconciliation_variance_cents": 0,
    }
    stamp_create(rec)
    db.production_days[rec["id"]] = rec
    return ok(ser.production_day_out(rec), 201)


@bp.route("/production-days", methods=["GET"])
def list_days():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager", "RouteDriver", "WholesaleClient"})
    records = list(db.production_days.values())
    st = request.args.get("status")
    if st is not None:
        records = [r for r in records if r["status"] == st]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.production_day_out(r) for r in page], limit, offset, total)


@bp.route("/production-days/<did>", methods=["GET"])
def get_day(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager", "RouteDriver", "WholesaleClient"})
    d = get_or_404(db.production_days, did)
    return ok(ser.production_day_out(d))


@bp.route("/production-days/<did>/start-baking", methods=["POST"])
def start_baking(did):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    d = get_or_404(db.production_days, did)
    if d["status"] != "OPEN":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be OPEN")
    if not any(b["production_day_id"] == did for b in db.bake_batches.values()):
        raise ApiError("ERR_NO_BATCHES", 409, "no batches on the day")
    d["status"] = "BAKING"
    touch(d)
    return ok(ser.production_day_out(d))


@bp.route("/production-days/<did>/open-sales", methods=["POST"])
def open_sales(did):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    d = get_or_404(db.production_days, did)
    if d["status"] != "BAKING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be BAKING")
    batches = [b for b in db.bake_batches.values() if b["production_day_id"] == did]
    if any(b["status"] == "PLANNED" for b in batches):
        raise ApiError("ERR_UNBAKED_BATCHES", 409, "all batches must be baked")
    d["status"] = "SELLING"
    touch(d)
    return ok(ser.production_day_out(d))


@bp.route("/production-days/<did>/close-cutoff", methods=["POST"])
def close_cutoff(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    d = get_or_404(db.production_days, did)
    if d["status"] != "SELLING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be SELLING")
    d["status"] = "CUTOFF"
    touch(d)
    return ok(ser.production_day_out(d))


@bp.route("/production-days/<did>/reconcile", methods=["POST"])
def reconcile(did):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    d = get_or_404(db.production_days, did)
    body = body_json()
    if body.get("expected_production_day_version") is None or \
            not _is_int(body["expected_production_day_version"]):
        raise ApiError("ERR_INVALID_REQUEST", 422, "expected_production_day_version required")
    if d["status"] != "CUTOFF":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be CUTOFF")
    batches = [b for b in db.bake_batches.values() if b["production_day_id"] == did]
    if any(b["status"] != "SWEPT" for b in batches):
        raise ApiError("ERR_BATCHES_NOT_SWEPT", 409, "every batch must be SWEPT")
    deliveries = [dl for dl in db.wholesale_deliveries.values() if dl["production_day_id"] == did]
    if any(dl["status"] in ("SCHEDULED", "PICKED", "DELIVERED") for dl in deliveries):
        raise ApiError("ERR_DELIVERIES_OPEN", 409, "open deliveries remain")
    if body["expected_production_day_version"] != d["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale production day version")

    # Compute pools
    expected = 0
    markdown_loss = 0
    waste = 0
    for b in batches:
        p = db.products[b["product_id"]]
        expected += b["baked_qty"] * p["unit_price_cents"]
        markdown_loss += b["markdown_sold_qty"] * (p["unit_price_cents"] - calc.markdown_price(p))
        if b["status"] == "SWEPT":
            waste += b["wasted_qty"] * p["unit_cost_cents"]
    gross = 0
    for o in db.retail_orders.values():
        if o["production_day_id"] == did and o["status"] == "PAID":
            gross += o["total_cents"]
    for dl in deliveries:
        if dl["status"] == "INVOICED":
            gross += dl["amount_cents"]

    d["expected_full_value_cents"] = expected
    d["gross_sales_cents"] = gross
    d["markdown_loss_cents"] = markdown_loss
    d["waste_cost_cents"] = waste
    d["reconciliation_variance_cents"] = expected - gross - markdown_loss - waste
    d["status"] = "RECONCILED"
    touch(d)
    return ok(ser.production_day_out(d))


# ===========================================================================
# Bake Batches
# ===========================================================================
@bp.route("/production-days/<did>/bake-batches", methods=["POST"])
def create_batch(did):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    d = get_or_404(db.production_days, did)
    body = body_json()
    require_fields(body, ["product_id", "par_qty"])
    if body["product_id"] not in db.products:
        raise ApiError("ERR_NOT_FOUND", 404, "product not found")
    if not _is_int(body["par_qty"]) or body["par_qty"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "par_qty must be integer >= 0")
    if not db.products[body["product_id"]]["active"]:
        raise ApiError("ERR_INVALID_REQUEST", 422, "product is retired")
    rec = {
        "production_day_id": did, "product_id": body["product_id"],
        "par_qty": body["par_qty"], "baked_qty": 0,
        "sold_qty": 0, "markdown_sold_qty": 0, "remaining_qty": 0, "wasted_qty": 0,
        "status": "PLANNED",
    }
    stamp_create(rec)
    db.bake_batches[rec["id"]] = rec
    return ok(ser.bake_batch_out(rec), 201)


@bp.route("/production-days/<did>/bake-batches", methods=["GET"])
def list_batches(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager"})
    get_or_404(db.production_days, did)
    records = [b for b in db.bake_batches.values() if b["production_day_id"] == did]
    pf = request.args.get("product_id")
    if pf is not None:
        records = [r for r in records if r["product_id"] == pf]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.bake_batch_out(r) for r in page], limit, offset, total)


def _get_batch(did, batch_id):
    get_or_404(db.production_days, did)
    b = db.bake_batches.get(batch_id)
    if b is None or b["production_day_id"] != did:
        raise ApiError("ERR_NOT_FOUND", 404, "batch not found")
    return b


@bp.route("/production-days/<did>/bake-batches/<batch_id>", methods=["GET"])
def get_batch(did, batch_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier", "BakeManager"})
    b = _get_batch(did, batch_id)
    return ok(ser.bake_batch_out(b))


@bp.route("/production-days/<did>/bake-batches/<batch_id>/bake", methods=["POST"])
def bake_batch(did, batch_id):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    b = _get_batch(did, batch_id)
    d = db.production_days[did]
    body = body_json()
    if body.get("baked_qty") is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "baked_qty required")
    if d["status"] != "BAKING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be BAKING")
    if b["status"] != "PLANNED":
        raise ApiError("ERR_BATCH_INVALID_STATE", 409, "batch must be PLANNED")
    if not _is_int(body["baked_qty"]) or body["baked_qty"] < 1:
        raise ApiError("ERR_INVALID_BAKE_QTY", 422, "baked_qty must be >= 1")
    b["baked_qty"] = body["baked_qty"]
    b["remaining_qty"] = body["baked_qty"]
    b["sold_qty"] = 0
    b["status"] = "BAKED"
    touch(b)
    return ok(ser.bake_batch_out(b))


@bp.route("/production-days/<did>/bake-batches/<batch_id>/markdown", methods=["POST"])
def markdown_batch(did, batch_id):
    uid, role = get_auth()
    require_roles(role, {"Cashier"})
    b = _get_batch(did, batch_id)
    d = db.production_days[did]
    if d["status"] != "SELLING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be SELLING")
    if b["status"] != "BAKED":
        raise ApiError("ERR_BATCH_INVALID_STATE", 409, "batch must be BAKED")
    if b["remaining_qty"] < 1:
        raise ApiError("ERR_NOTHING_TO_MARK_DOWN", 409, "nothing to mark down")
    b["status"] = "MARKED_DOWN"
    touch(b)
    return ok(ser.bake_batch_out(b))


@bp.route("/production-days/<did>/bake-batches/<batch_id>/sweep", methods=["POST"])
def sweep_batch(did, batch_id):
    uid, role = get_auth()
    require_roles(role, {"BakeManager"})
    b = _get_batch(did, batch_id)
    d = db.production_days[did]
    if d["status"] not in ("SELLING", "CUTOFF"):
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be SELLING or CUTOFF")
    if b["status"] not in ("BAKED", "MARKED_DOWN"):
        raise ApiError("ERR_BATCH_INVALID_STATE", 409, "batch must be BAKED or MARKED_DOWN")
    b["wasted_qty"] = b["remaining_qty"]
    b["status"] = "SWEPT"
    touch(b)
    # Sweeping freezes waste and bumps the day (affects OCC on reconcile)
    touch(d)
    return ok(ser.bake_batch_out(b))


# ===========================================================================
# Retail Orders
# ===========================================================================
@bp.route("/production-days/<did>/retail-orders", methods=["POST"])
def create_retail_order(did):
    uid, role = get_auth()
    require_roles(role, {"Cashier"})
    d = get_or_404(db.production_days, did)
    body = body_json()
    if body.get("line_items") is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "line_items required")
    line_items = body["line_items"]
    _validate_line_items(line_items, allow_marked_down=True)
    _check_products_exist(line_items)
    loyalty_id = body.get("loyalty_account_id")
    if loyalty_id is not None and loyalty_id not in db.loyalty_accounts:
        raise ApiError("ERR_NOT_FOUND", 404, "loyalty account not found")
    _require_active_products(line_items)
    redeem = bool(body.get("redeem_reward", False))

    norm_items = [{"product_id": li["product_id"], "qty": li["qty"],
                   "marked_down": bool(li.get("marked_down", False))} for li in line_items]
    subtotal = calc.lines_subtotal(norm_items)
    rec = {
        "production_day_id": did, "loyalty_account_id": loyalty_id,
        "line_items": norm_items, "subtotal_cents": subtotal,
        "loyalty_discount_cents": 0, "total_cents": subtotal,
        "redeem_reward": redeem, "status": "CART",
        # internal cascade bookkeeping
        "_earned": 0, "_conversions": 0, "_redeemed": 0,
    }
    stamp_create(rec)
    db.retail_orders[rec["id"]] = rec
    return ok(ser.retail_order_out(rec), 201)


@bp.route("/production-days/<did>/retail-orders", methods=["GET"])
def list_retail_orders(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier"})
    get_or_404(db.production_days, did)
    records = [o for o in db.retail_orders.values() if o["production_day_id"] == did]
    st = request.args.get("status")
    if st is not None:
        records = [r for r in records if r["status"] == st]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.retail_order_out(r) for r in page], limit, offset, total)


def _get_order(did, order_id):
    get_or_404(db.production_days, did)
    o = db.retail_orders.get(order_id)
    if o is None or o["production_day_id"] != did:
        raise ApiError("ERR_NOT_FOUND", 404, "order not found")
    return o


@bp.route("/production-days/<did>/retail-orders/<order_id>", methods=["GET"])
def get_retail_order(did, order_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "Cashier"})
    o = _get_order(did, order_id)
    return ok(ser.retail_order_out(o))


def _batch_for_product(did, product_id):
    for b in db.bake_batches.values():
        if b["production_day_id"] == did and b["product_id"] == product_id:
            return b
    return None


@bp.route("/production-days/<did>/retail-orders/<order_id>/pay", methods=["POST"])
def pay_retail_order(did, order_id):
    uid, role = get_auth()
    require_roles(role, {"Cashier"})
    o = _get_order(did, order_id)
    d = db.production_days[did]
    if d["status"] != "SELLING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be SELLING")
    if o["status"] != "CART":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "order must be CART")

    # Resolve batches and aggregate required quantities per batch
    # Priority 12: markdown stock checks first; priority 13: full-price stock checks.
    # Markdown lines.
    for li in o["line_items"]:
        if li["marked_down"]:
            b = _batch_for_product(did, li["product_id"])
            if b is None or b["status"] != "MARKED_DOWN" or b["remaining_qty"] < li["qty"]:
                raise ApiError("ERR_INSUFFICIENT_MARKDOWN_STOCK", 409,
                               "insufficient markdown stock")
    # All lines: stock availability.
    for li in o["line_items"]:
        b = _batch_for_product(did, li["product_id"])
        if b is None or b["remaining_qty"] < li["qty"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient stock")

    # Recompute totals + loyalty redemption (order pinned: subtotal, redeem, total)
    subtotal = calc.lines_subtotal(o["line_items"])
    loyalty_discount = 0
    redeemed = 0
    acct = db.loyalty_accounts.get(o["loyalty_account_id"]) if o["loyalty_account_id"] else None
    if o["redeem_reward"] and acct is not None and acct["reward_balance_cents"] >= REWARD_VALUE_CENTS:
        loyalty_discount = min(REWARD_VALUE_CENTS, subtotal)
        redeemed = REWARD_VALUE_CENTS
        acct["reward_balance_cents"] -= REWARD_VALUE_CENTS
        touch(acct)
    total = max(0, subtotal - loyalty_discount)

    # Stock cascade
    for li in o["line_items"]:
        b = _batch_for_product(did, li["product_id"])
        b["sold_qty"] += li["qty"]
        b["remaining_qty"] = b["baked_qty"] - b["sold_qty"]
        if b["remaining_qty"] < 0:
            b["remaining_qty"] = 0
        if li["marked_down"]:
            b["markdown_sold_qty"] += li["qty"]
        touch(b)

    # Loyalty accrual cascade
    earned = 0
    conversions = 0
    if acct is not None:
        total_qty = sum(li["qty"] for li in o["line_items"])
        earned, conversions = calc.apply_loyalty_accrual(acct, total_qty)
        touch(acct)

    o["subtotal_cents"] = subtotal
    o["loyalty_discount_cents"] = loyalty_discount
    o["total_cents"] = total
    o["status"] = "PAID"
    o["_earned"] = earned
    o["_conversions"] = conversions
    o["_redeemed"] = redeemed
    touch(o)
    return ok(ser.retail_order_out(o))


def _reverse_order(o, did):
    """Compensation shared by void and refund."""
    acct = db.loyalty_accounts.get(o["loyalty_account_id"]) if o["loyalty_account_id"] else None
    # Restore stock
    for li in o["line_items"]:
        b = _batch_for_product(did, li["product_id"])
        if b is not None:
            b["sold_qty"] -= li["qty"]
            if b["sold_qty"] < 0:
                b["sold_qty"] = 0
            b["remaining_qty"] = b["baked_qty"] - b["sold_qty"]
            if b["remaining_qty"] < 0:
                b["remaining_qty"] = 0
            if li["marked_down"]:
                b["markdown_sold_qty"] -= li["qty"]
                if b["markdown_sold_qty"] < 0:
                    b["markdown_sold_qty"] = 0
            touch(b)
    # Reverse loyalty accrual
    if acct is not None:
        calc.reverse_loyalty_accrual(acct, o.get("_earned", 0), o.get("_conversions", 0))
        # Refund any redeemed reward
        if o.get("_redeemed", 0):
            acct["reward_balance_cents"] += o["_redeemed"]
        touch(acct)


@bp.route("/production-days/<did>/retail-orders/<order_id>/void", methods=["POST"])
def void_retail_order(did, order_id):
    uid, role = get_auth()
    require_roles(role, {"Cashier"})
    o = _get_order(did, order_id)
    d = db.production_days[did]
    if d["status"] != "SELLING":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "day must be SELLING")
    if o["status"] != "PAID":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "order must be PAID")
    _reverse_order(o, did)
    o["status"] = "VOIDED"
    touch(o)
    return ok(ser.retail_order_out(o))


@bp.route("/production-days/<did>/retail-orders/<order_id>/refund", methods=["POST"])
def refund_retail_order(did, order_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    o = _get_order(did, order_id)
    if o["status"] != "PAID":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "order must be PAID")
    _reverse_order(o, did)
    o["status"] = "REFUNDED"
    touch(o)
    return ok(ser.retail_order_out(o))


# ===========================================================================
# Loyalty Accounts
# ===========================================================================
@bp.route("/loyalty-accounts", methods=["POST"])
def create_loyalty():
    uid, role = get_auth()
    require_roles(role, {"Cashier", "ShopAdmin"})
    body = body_json()
    require_fields(body, ["phone", "name"])
    if any(a["phone"] == body["phone"] for a in db.loyalty_accounts.values()):
        raise ApiError("ERR_INVALID_REQUEST", 422, "phone must be unique")
    rec = {"phone": body["phone"], "name": body["name"],
           "punch_count": 0, "reward_balance_cents": 0}
    stamp_create(rec)
    db.loyalty_accounts[rec["id"]] = rec
    return ok(ser.loyalty_account_out(rec), 201)


@bp.route("/loyalty-accounts/<aid>", methods=["GET"])
def get_loyalty(aid):
    uid, role = get_auth()
    require_roles(role, {"Cashier", "ShopAdmin"})
    a = get_or_404(db.loyalty_accounts, aid)
    return ok(ser.loyalty_account_out(a))


@bp.route("/loyalty-accounts/<aid>/retail-orders", methods=["GET"])
def list_loyalty_orders(aid):
    uid, role = get_auth()
    require_roles(role, {"Cashier", "ShopAdmin"})
    get_or_404(db.loyalty_accounts, aid)
    records = [o for o in db.retail_orders.values() if o["loyalty_account_id"] == aid]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.retail_order_out(r) for r in page], limit, offset, total)


# ===========================================================================
# Wholesale Accounts
# ===========================================================================
@bp.route("/wholesale-accounts", methods=["POST"])
def create_wholesale_account():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    body = body_json()
    require_fields(body, ["name", "discount_pct", "credit_limit_cents"])
    dp = body["discount_pct"]
    if not isinstance(dp, (int, float)) or isinstance(dp, bool) or dp < 0 or dp >= 1:
        raise ApiError("ERR_INVALID_REQUEST", 422, "discount_pct must be 0 <= x < 1")
    if not _is_int(body["credit_limit_cents"]) or body["credit_limit_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "credit_limit_cents must be integer >= 0")
    rec = {"name": body["name"], "discount_pct": dp,
           "credit_limit_cents": body["credit_limit_cents"],
           "outstanding_balance_cents": 0, "status": "ACTIVE"}
    stamp_create(rec)
    db.wholesale_accounts[rec["id"]] = rec
    return ok(ser.wholesale_account_out(rec), 201)


@bp.route("/wholesale-accounts/<aid>", methods=["GET"])
def get_wholesale_account(aid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    a = get_or_404(db.wholesale_accounts, aid)
    _client_owns(role, uid, aid)
    return ok(ser.wholesale_account_out(a))


@bp.route("/wholesale-accounts/<aid>/wholesale-deliveries", methods=["GET"])
def list_account_deliveries(aid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    get_or_404(db.wholesale_accounts, aid)
    _client_owns(role, uid, aid)
    records = [dl for dl in db.wholesale_deliveries.values() if dl["wholesale_account_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        records = [r for r in records if r["status"] == st]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.wholesale_delivery_out(r) for r in page], limit, offset, total)


@bp.route("/wholesale-accounts/<aid>/suspend", methods=["POST"])
def suspend_account(aid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    a = get_or_404(db.wholesale_accounts, aid)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_INVALID_STATE", 409, "account must be ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    return ok(ser.wholesale_account_out(a))


@bp.route("/wholesale-accounts/<aid>/reactivate", methods=["POST"])
def reactivate_account(aid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    a = get_or_404(db.wholesale_accounts, aid)
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_INVALID_STATE", 409, "account must be SUSPENDED")
    a["status"] = "ACTIVE"
    touch(a)
    return ok(ser.wholesale_account_out(a))


@bp.route("/wholesale-accounts/<aid>/payments", methods=["POST"])
def record_payment(aid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    a = get_or_404(db.wholesale_accounts, aid)
    body = body_json()
    require_fields(body, ["amount_cents"])
    if not _is_int(body["amount_cents"]) or body["amount_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "amount_cents must be integer >= 0")
    db.wholesale_payments.append({"account_id": aid, "amount_cents": body["amount_cents"]})
    a["outstanding_balance_cents"] -= body["amount_cents"]
    touch(a)
    return ok(ser.wholesale_account_out(a))


# ===========================================================================
# Standing Orders
# ===========================================================================
@bp.route("/standing-orders", methods=["POST"])
def create_standing_order():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    body = body_json()
    require_fields(body, ["wholesale_account_id", "delivery_dow", "line_items"])
    if body["wholesale_account_id"] not in db.wholesale_accounts:
        raise ApiError("ERR_NOT_FOUND", 404, "wholesale account not found")
    _client_owns(role, uid, body["wholesale_account_id"])
    dow = body["delivery_dow"]
    if not _is_int(dow) or dow < 0 or dow > 6:
        raise ApiError("ERR_INVALID_REQUEST", 422, "delivery_dow must be 0..6")
    line_items = body["line_items"]
    _validate_line_items(line_items, allow_marked_down=False)
    _check_products_exist(line_items)
    norm = [{"product_id": li["product_id"], "qty": li["qty"]} for li in line_items]
    rec = {"wholesale_account_id": body["wholesale_account_id"], "delivery_dow": dow,
           "line_items": norm, "status": "ACTIVE"}
    stamp_create(rec)
    db.standing_orders[rec["id"]] = rec
    return ok(ser.standing_order_out(rec), 201)


@bp.route("/standing-orders", methods=["GET"])
def list_standing_orders():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    records = list(db.standing_orders.values())
    if role == "WholesaleClient":
        records = [r for r in records if r["wholesale_account_id"] == uid]
    af = request.args.get("wholesale_account_id")
    if af is not None:
        records = [r for r in records if r["wholesale_account_id"] == af]
    st = request.args.get("status")
    if st is not None:
        records = [r for r in records if r["status"] == st]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.standing_order_out(r) for r in page], limit, offset, total)


@bp.route("/standing-orders/<sid>", methods=["GET"])
def get_standing_order(sid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    s = get_or_404(db.standing_orders, sid)
    _client_owns(role, uid, s["wholesale_account_id"])
    return ok(ser.standing_order_out(s))


@bp.route("/standing-orders/<sid>/wholesale-deliveries", methods=["GET"])
def list_standing_order_deliveries(sid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    s = get_or_404(db.standing_orders, sid)
    _client_owns(role, uid, s["wholesale_account_id"])
    records = [dl for dl in db.wholesale_deliveries.values() if dl["standing_order_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        records = [r for r in records if r["status"] == st]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.wholesale_delivery_out(r) for r in page], limit, offset, total)


@bp.route("/standing-orders/<sid>/pause", methods=["POST"])
def pause_standing_order(sid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    s = get_or_404(db.standing_orders, sid)
    _client_owns(role, uid, s["wholesale_account_id"])
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_STANDING_ORDER_NOT_ACTIVE", 409, "standing order must be ACTIVE")
    s["status"] = "PAUSED"
    touch(s)
    return ok(ser.standing_order_out(s))


@bp.route("/standing-orders/<sid>/resume", methods=["POST"])
def resume_standing_order(sid):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    s = get_or_404(db.standing_orders, sid)
    _client_owns(role, uid, s["wholesale_account_id"])
    if s["status"] != "PAUSED":
        raise ApiError("ERR_STANDING_ORDER_NOT_ACTIVE", 409, "standing order must be PAUSED")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(ser.standing_order_out(s))


# ===========================================================================
# Wholesale Deliveries
# ===========================================================================
@bp.route("/production-days/<did>/wholesale-deliveries", methods=["POST"])
def release_delivery(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver"})
    d = get_or_404(db.production_days, did)
    body = body_json()
    require_fields(body, ["standing_order_id", "route_window_start", "route_window_end"])
    s = db.standing_orders.get(body["standing_order_id"])
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "standing order not found")
    # window well-formedness
    try:
        ws = parse_iso(body["route_window_start"])
        we = parse_iso(body["route_window_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid window timestamps")
    if not (we > ws):
        raise ApiError("ERR_INVALID_WINDOW", 422, "route_window_end must be after start")

    # Priority 7: cutoff / day state
    if d["status"] in ("CUTOFF", "RECONCILED"):
        raise ApiError("ERR_PAST_DELIVERY_CUTOFF", 409, "day past cutoff")
    clock = parse_iso(db.clock)
    if clock > parse_iso(d["delivery_cutoff_utc"]):
        raise ApiError("ERR_PAST_DELIVERY_CUTOFF", 409, "past delivery cutoff")
    # Priority 8: standing order ACTIVE
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_STANDING_ORDER_NOT_ACTIVE", 409, "standing order not ACTIVE")
    acct = db.wholesale_accounts[s["wholesale_account_id"]]
    # Priority 9: account ACTIVE
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "account suspended")
    # Priority 10: route window conflict (buffer, closed intervals, same account+day)
    buf = timedelta(minutes=ROUTE_BUFFER_MINUTES)
    for dl in db.wholesale_deliveries.values():
        if dl["production_day_id"] != did or dl["wholesale_account_id"] != acct["id"]:
            continue
        if dl["status"] not in ("SCHEDULED", "PICKED", "DELIVERED"):
            continue
        es = parse_iso(dl["route_window_start"])
        ee = parse_iso(dl["route_window_end"])
        if ws <= ee + buf and es <= we + buf:
            raise ApiError("ERR_ROUTE_WINDOW_CONFLICT", 409, "route window conflict")

    amount = calc.wholesale_delivery_amount(s["line_items"], acct["discount_pct"])
    rec = {"production_day_id": did, "standing_order_id": s["id"],
           "wholesale_account_id": acct["id"],
           "route_window_start": body["route_window_start"],
           "route_window_end": body["route_window_end"],
           "amount_cents": amount, "status": "SCHEDULED"}
    stamp_create(rec)
    db.wholesale_deliveries[rec["id"]] = rec
    return ok(ser.wholesale_delivery_out(rec), 201)


@bp.route("/production-days/<did>/wholesale-deliveries", methods=["GET"])
def list_day_deliveries(did):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    get_or_404(db.production_days, did)
    records = [dl for dl in db.wholesale_deliveries.values() if dl["production_day_id"] == did]
    if role == "WholesaleClient":
        records = [r for r in records if r["wholesale_account_id"] == uid]
    for key in ("standing_order_id", "wholesale_account_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.wholesale_delivery_out(r) for r in page], limit, offset, total)


def _get_delivery(did, delivery_id):
    get_or_404(db.production_days, did)
    dl = db.wholesale_deliveries.get(delivery_id)
    if dl is None or dl["production_day_id"] != did:
        raise ApiError("ERR_NOT_FOUND", 404, "delivery not found")
    return dl


@bp.route("/production-days/<did>/wholesale-deliveries/<delivery_id>", methods=["GET"])
def get_delivery(did, delivery_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "RouteDriver", "WholesaleClient"})
    dl = _get_delivery(did, delivery_id)
    _client_owns(role, uid, dl["wholesale_account_id"])
    return ok(ser.wholesale_delivery_out(dl))


@bp.route("/production-days/<did>/wholesale-deliveries/<delivery_id>/pick", methods=["POST"])
def pick_delivery(did, delivery_id):
    uid, role = get_auth()
    require_roles(role, {"RouteDriver"})
    dl = _get_delivery(did, delivery_id)
    if dl["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_INVALID_STATE", 409, "delivery must be SCHEDULED")
    dl["status"] = "PICKED"
    touch(dl)
    return ok(ser.wholesale_delivery_out(dl))


@bp.route("/production-days/<did>/wholesale-deliveries/<delivery_id>/deliver", methods=["POST"])
def deliver_delivery(did, delivery_id):
    uid, role = get_auth()
    require_roles(role, {"RouteDriver"})
    dl = _get_delivery(did, delivery_id)
    if dl["status"] != "PICKED":
        raise ApiError("ERR_DELIVERY_INVALID_STATE", 409, "delivery must be PICKED")
    dl["status"] = "DELIVERED"
    touch(dl)
    return ok(ser.wholesale_delivery_out(dl))


@bp.route("/production-days/<did>/wholesale-deliveries/<delivery_id>/invoice", methods=["POST"])
def invoice_delivery(did, delivery_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    dl = _get_delivery(did, delivery_id)
    if dl["status"] != "DELIVERED":
        raise ApiError("ERR_DELIVERY_INVALID_STATE", 409, "delivery must be DELIVERED")
    acct = db.wholesale_accounts[dl["wholesale_account_id"]]
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "account suspended")
    if acct["outstanding_balance_cents"] + dl["amount_cents"] > acct["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402, "credit limit exceeded")
    dl["status"] = "INVOICED"
    touch(dl)
    acct["outstanding_balance_cents"] += dl["amount_cents"]
    touch(acct)
    return ok(ser.wholesale_delivery_out(dl))


@bp.route("/production-days/<did>/wholesale-deliveries/<delivery_id>/cancel", methods=["POST"])
def cancel_delivery(did, delivery_id):
    uid, role = get_auth()
    require_roles(role, {"RouteDriver"})
    dl = _get_delivery(did, delivery_id)
    if dl["status"] not in ("SCHEDULED", "PICKED"):
        raise ApiError("ERR_DELIVERY_INVALID_STATE", 409, "delivery must be SCHEDULED or PICKED")
    dl["status"] = "CANCELLED"
    touch(dl)
    return ok(ser.wholesale_delivery_out(dl))


# ===========================================================================
# Pre-Orders
# ===========================================================================
@bp.route("/pre-orders", methods=["POST"])
def create_preorder():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    body = body_json()
    require_fields(body, ["wholesale_account_id", "pickup_production_day_id",
                          "pickup_window_start", "pickup_window_end", "line_items"])
    if body["wholesale_account_id"] not in db.wholesale_accounts:
        raise ApiError("ERR_NOT_FOUND", 404, "wholesale account not found")
    if body["pickup_production_day_id"] not in db.production_days:
        raise ApiError("ERR_NOT_FOUND", 404, "production day not found")
    _client_owns(role, uid, body["wholesale_account_id"])
    line_items = body["line_items"]
    _validate_line_items(line_items, allow_marked_down=False)
    _check_products_exist(line_items)
    try:
        ws = parse_iso(body["pickup_window_start"])
        we = parse_iso(body["pickup_window_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid pickup window")
    if not (we > ws):
        raise ApiError("ERR_INVALID_WINDOW", 422, "pickup_window_end must be after start")

    # Catering slot overlap (half-open intervals)
    day_id = body["pickup_production_day_id"]
    overlapping = 0
    for p in db.pre_orders.values():
        if p["pickup_production_day_id"] != day_id or p["status"] == "CANCELLED":
            continue
        ps = parse_iso(p["pickup_window_start"])
        pe = parse_iso(p["pickup_window_end"])
        if ps < we and ws < pe:
            overlapping += 1
    if overlapping >= CATERING_SLOT_CAPACITY:
        raise ApiError("ERR_CATERING_SLOT_FULL", 409, "catering slot full")

    norm = [{"product_id": li["product_id"], "qty": li["qty"]} for li in line_items]
    subtotal = calc.lines_subtotal(norm)
    deposit_due = calc.preorder_deposit(subtotal)
    rec = {"wholesale_account_id": body["wholesale_account_id"],
           "pickup_production_day_id": day_id,
           "pickup_window_start": body["pickup_window_start"],
           "pickup_window_end": body["pickup_window_end"],
           "line_items": norm, "subtotal_cents": subtotal,
           "deposit_due_cents": deposit_due, "deposit_paid_cents": 0,
           "status": "REQUESTED"}
    stamp_create(rec)
    db.pre_orders[rec["id"]] = rec
    return ok(ser.pre_order_out(rec), 201)


@bp.route("/pre-orders", methods=["GET"])
def list_preorders():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    records = list(db.pre_orders.values())
    if role == "WholesaleClient":
        records = [r for r in records if r["wholesale_account_id"] == uid]
    for key in ("wholesale_account_id", "pickup_production_day_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    records = sort_by_created(records)
    page, limit, offset, total = paginate(records)
    return ok_list([ser.pre_order_out(r) for r in page], limit, offset, total)


@bp.route("/pre-orders/<pre_id>", methods=["GET"])
def get_preorder(pre_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    p = get_or_404(db.pre_orders, pre_id)
    _client_owns(role, uid, p["wholesale_account_id"])
    return ok(ser.pre_order_out(p))


@bp.route("/pre-orders/<pre_id>/deposit", methods=["POST"])
def deposit_preorder(pre_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    p = get_or_404(db.pre_orders, pre_id)
    _client_owns(role, uid, p["wholesale_account_id"])
    body = body_json()
    require_fields(body, ["amount_cents"])
    if not _is_int(body["amount_cents"]) or body["amount_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "amount_cents must be integer >= 0")
    p["deposit_paid_cents"] += body["amount_cents"]
    touch(p)
    return ok(ser.pre_order_out(p))


@bp.route("/pre-orders/<pre_id>/confirm", methods=["POST"])
def confirm_preorder(pre_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    p = get_or_404(db.pre_orders, pre_id)
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order must be REQUESTED")
    day = db.production_days[p["pickup_production_day_id"]]
    if day["status"] == "RECONCILED":
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "pickup day is RECONCILED")
    if p["deposit_paid_cents"] < p["deposit_due_cents"]:
        raise ApiError("ERR_DEPOSIT_NOT_MET", 402, "deposit not met")
    p["status"] = "CONFIRMED"
    touch(p)
    return ok(ser.pre_order_out(p))


@bp.route("/pre-orders/<pre_id>/fulfill", methods=["POST"])
def fulfill_preorder(pre_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    p = get_or_404(db.pre_orders, pre_id)
    if p["status"] != "CONFIRMED":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order must be CONFIRMED")
    day = db.production_days[p["pickup_production_day_id"]]
    if day["status"] not in ("SELLING", "CUTOFF"):
        raise ApiError("ERR_DAY_INVALID_STATE", 409, "pickup day must be SELLING or CUTOFF")
    p["status"] = "FULFILLED"
    touch(p)
    return ok(ser.pre_order_out(p))


@bp.route("/pre-orders/<pre_id>/cancel", methods=["POST"])
def cancel_preorder(pre_id):
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin", "WholesaleClient"})
    p = get_or_404(db.pre_orders, pre_id)
    _client_owns(role, uid, p["wholesale_account_id"])
    if p["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order must be REQUESTED or CONFIRMED")
    p["status"] = "CANCELLED"
    touch(p)
    return ok(ser.pre_order_out(p))


# ===========================================================================
# Logical clock
# ===========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_auth()
    require_roles(role, {"ShopAdmin"})
    body = body_json()
    require_fields(body, ["to_iso8601"])
    try:
        parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid to_iso8601")
    db.clock = body["to_iso8601"]
    return ok({})
