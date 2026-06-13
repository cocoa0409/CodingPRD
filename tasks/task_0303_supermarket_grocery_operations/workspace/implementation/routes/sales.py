"""Point of sale: sales, line items, finalize, void, pay, refund."""
from flask import Blueprint, request, g

from auth import require_role
from common import (
    stamp_new, touch, require_dict, get_int, pagination_params, paginate,
    round_half_up,
)
from clock import clock
from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST,
    ERR_SALE_NOT_OPEN, ERR_SALE_EMPTY, ERR_SALE_NOT_FINALIZED,
    ERR_SALE_NOT_UNPAID, ERR_SALE_NOT_PAID,
    ERR_MEMBER_NOT_ACTIVE, ERR_LINE_UNIT_MISMATCH, ERR_COUPON_NOT_REDEEMABLE,
    ERR_INSUFFICIENT_STOCK,
)
from lookup import get_sale, get_sale_line, get_product, get_member, get_clip
from inventory import (
    product_inventory_rollup, fefo_eligible_lots, fefo_available, fefo_deplete,
)
from routes.loyalty import recompute_tier
from response import success, list_response
from serializers import ser_sale, ser_sale_line

bp = Blueprint("sales", __name__)


def _window_covers(rec, now):
    return rec["_effective_start_dt"] <= now < rec["_effective_end_dt"]


# ---------------- Open / list / get ----------------

@bp.route("/sales", methods=["POST"])
def open_sale():
    require_role("Cashier", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    member_id = body.get("member_id")
    if member_id is not None:
        if not isinstance(member_id, str):
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "member_id must be a string")
        get_member(member_id)
    rec = stamp_new({
        "member_id": member_id,
        "clipped_coupon_id": None,
        "subtotal_cents": 0,
        "coupon_discount_cents": 0,
        "total_cents": 0,
        "cogs_cents": 0,
        "points_earned": 0,
        "tender_status": "UNPAID",
        "fulfillment_status": "OPEN",
    })
    db.sales[rec["id"]] = rec
    return success(ser_sale(rec), status=201)


@bp.route("/sales", methods=["GET"])
def list_sales():
    require_role("Cashier", "StoreManager", "InventoryAuditor")
    limit, offset = pagination_params(request.args)
    items = list(db.sales.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [s for s in items if s.get("member_id") == member_id]
    clip_id = request.args.get("clipped_coupon_id")
    if clip_id is not None:
        items = [s for s in items if s.get("clipped_coupon_id") == clip_id]
    tender = request.args.get("tender_status")
    if tender is not None:
        items = [s for s in items if s["tender_status"] == tender]
    fulfillment = request.args.get("fulfillment_status")
    if fulfillment is not None:
        items = [s for s in items if s["fulfillment_status"] == fulfillment]
    page, total = paginate(items, limit, offset)
    return list_response([ser_sale(s) for s in page], limit, offset, total)


@bp.route("/sales/<sid>", methods=["GET"])
def get_sale_route(sid):
    require_role("Cashier", "StoreManager", "InventoryAuditor")
    s = get_sale(sid)
    return success(ser_sale(s))


# ---------------- Line items ----------------

@bp.route("/sales/<sid>/line-items", methods=["POST"])
def add_line_item(sid):
    require_role("Cashier", "StoreManager")
    s = get_sale(sid)
    body = require_dict(request.get_json(silent=True))
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    product = get_product(product_id)

    quantity = get_int(body, "quantity", required=False, default=None, min_value=1)
    weight_milli = get_int(body, "weight_milli", required=False, default=None, min_value=1)

    # State (priority 6): adding a line requires fulfillment OPEN
    if s["fulfillment_status"] != "OPEN":
        raise ApiError(ERR_SALE_NOT_OPEN[0], ERR_SALE_NOT_OPEN[1], "sale not open")

    # well-formedness: exactly the right measure present (priority 4 in general),
    # but unit-type-mismatch (priority 8) is its own error class.
    if product["sell_by_weight"]:
        if quantity is not None:
            raise ApiError(ERR_LINE_UNIT_MISMATCH[0], ERR_LINE_UNIT_MISMATCH[1], "weighed product requires weight_milli")
        if weight_milli is None:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "weight_milli required for weighed product")
    else:
        if weight_milli is not None:
            raise ApiError(ERR_LINE_UNIT_MISMATCH[0], ERR_LINE_UNIT_MISMATCH[1], "each-sold product requires quantity")
        if quantity is None:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "quantity required for each-sold product")

    rec = stamp_new({
        "sale_id": sid,
        "product_id": product_id,
        "quantity": quantity,
        "weight_milli": weight_milli,
        "unit_price_applied_cents": None,
        "extended_price_cents": None,
        "promo_id_applied": None,
    })
    db.sale_line_items[rec["id"]] = rec
    return success(ser_sale_line(rec), status=201)


@bp.route("/sale-line-items/<lid>", methods=["GET"])
def get_sale_line_route(lid):
    require_role("Cashier", "StoreManager", "InventoryAuditor")
    line = get_sale_line(lid)
    return success(ser_sale_line(line))


@bp.route("/sale-line-items", methods=["GET"])
def list_sale_lines():
    require_role("Cashier", "StoreManager", "InventoryAuditor")
    limit, offset = pagination_params(request.args)
    items = list(db.sale_line_items.values())
    sale_id = request.args.get("sale_id")
    if sale_id is not None:
        items = [l for l in items if l["sale_id"] == sale_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    page, total = paginate(items, limit, offset)
    return list_response([ser_sale_line(l) for l in page], limit, offset, total)


# ---------------- Pricing helpers ----------------

def _lines_of(sid):
    lines = [l for l in db.sale_line_items.values() if l["sale_id"] == sid]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    return lines


def select_effective_unit_price(product, now):
    """Lowest ad_price_cents among price plans whose half-open window covers the
    clock; tie-break effective_start DESC then created_at ASC. Else everyday price.
    Returns (unit_price, ad_applied: bool)."""
    candidates = [
        pp for pp in db.price_plans.values()
        if pp["product_id"] == product["id"]
        and pp["status"] != "CANCELLED"
        and _window_covers(pp, now)
    ]
    if not candidates:
        return product["unit_price_cents"], False

    def key(pp):
        # min ad_price; tie-break later effective_start, then earlier created_at
        return (pp["ad_price_cents"], -pp["_effective_start_dt"].timestamp(), pp["created_at"], pp.get("_seq", 0))

    best = min(candidates, key=key)
    return best["ad_price_cents"], True


def select_promotion(product, line_qty, gross, unit_price, ad_applied, now):
    """Choose at most one eligible promotion yielding the largest discount.
    Tie-break by later effective_start, then earlier created_at.
    Returns (promo_id or None, discount)."""
    best_pr = None
    best_discount = 0
    best_key = None
    for pr in db.promotions.values():
        if pr["product_id"] != product["id"]:
            continue
        if pr["status"] == "CANCELLED":
            continue
        if not _window_covers(pr, now):
            continue
        # each-sold min_qty threshold (weighed items ignore min_qty)
        if not product["sell_by_weight"]:
            if line_qty is None or line_qty < pr["min_qty"]:
                continue
        # stacking: stackable OR no ad price plan was applied to this line
        if ad_applied and not pr["stackable"]:
            continue
        discount = _promo_discount(pr, product, line_qty, gross, unit_price)
        # Higher discount preferred; tie -> later effective_start; tie -> earlier
        # created_at/seq (negate seq so smaller seq ranks higher).
        key = (discount, pr["_effective_start_dt"].timestamp(), -(pr.get("_seq", 0)))
        if best_key is None or key > best_key:
            best_key = key
            best_pr = pr
            best_discount = discount

    if best_pr is None:
        return None, 0
    return best_pr["id"], best_discount


def _promo_discount(pr, product, line_qty, gross, unit_price):
    ptype = pr["promo_type"]
    if ptype == "PERCENT_OFF":
        return round_half_up(gross * pr["percent_off_bps"], 10000)
    if ptype == "FIXED_OFF":
        # each-sold only
        return min(gross, pr["fixed_off_cents"] * (line_qty or 0))
    if ptype == "BOGO":
        free_units = (line_qty or 0) // 2
        return free_units * unit_price
    return 0


def _price_line(line, product, now):
    """Pure computation: returns (unit_price, extended_price, promo_id, ad_applied)."""
    unit_price, ad_applied = select_effective_unit_price(product, now)
    if product["sell_by_weight"]:
        gross = round_half_up(unit_price * line["weight_milli"], 1000)
        line_qty = None
    else:
        gross = unit_price * line["quantity"]
        line_qty = line["quantity"]
    promo_id, discount = select_promotion(product, line_qty, gross, unit_price, ad_applied, now)
    extended = max(0, gross - discount)
    return unit_price, extended, promo_id, ad_applied


# ---------------- Finalize ----------------

@bp.route("/sales/<sid>/finalize", methods=["POST"])
def finalize_sale(sid):
    require_role("Cashier", "StoreManager")
    s = get_sale(sid)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "request body must be a JSON object")
    clipped_coupon_id = body.get("clipped_coupon_id")
    clip = None
    if clipped_coupon_id is not None:
        if not isinstance(clipped_coupon_id, str):
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "clipped_coupon_id must be a string")
        clip = get_clip(clipped_coupon_id)  # FK existence (priority 3)

    # State (priority 6)
    if s["fulfillment_status"] != "OPEN":
        raise ApiError(ERR_SALE_NOT_OPEN[0], ERR_SALE_NOT_OPEN[1], "sale not open")
    lines = _lines_of(sid)
    if len(lines) < 1:
        raise ApiError(ERR_SALE_EMPTY[0], ERR_SALE_EMPTY[1], "sale has no line items")

    member = None
    if s.get("member_id"):
        member = get_member(s["member_id"])
        if member["status"] != "ACTIVE":
            raise ApiError(ERR_MEMBER_NOT_ACTIVE[0], ERR_MEMBER_NOT_ACTIVE[1], "member not active")

    now = clock.now()

    # --- Price all lines (pure computation, no mutation) ---
    priced = []  # (line, product, unit_price, extended, promo_id)
    for line in lines:
        product = db.products.get(line["product_id"])
        unit_price, extended, promo_id, ad_applied = _price_line(line, product, now)
        priced.append((line, product, unit_price, extended, promo_id))

    subtotal = sum(p[3] for p in priced)

    # --- Coupon gate (priority 10) against subtotal ---
    coupon_discount = 0
    if clip is not None:
        coupon = db.coupons.get(clip["coupon_id"])
        ok = True
        if clip["member_id"] != s.get("member_id"):
            ok = False
        elif clip["status"] != "CLIPPED":
            ok = False
        elif coupon is None or not _window_covers(coupon, now):
            ok = False
        elif subtotal < coupon["min_spend_cents"]:
            ok = False
        else:
            # stacking: stackable OR no line applied a promo to the coupon's product
            if not coupon["stackable"]:
                for (ln, prod, up, ext, pid) in priced:
                    if pid is not None and ln["product_id"] == coupon["product_id"]:
                        ok = False
                        break
        if not ok:
            raise ApiError(ERR_COUPON_NOT_REDEEMABLE[0], ERR_COUPON_NOT_REDEEMABLE[1], "coupon not redeemable")
        coupon_discount = min(coupon["discount_cents"], subtotal)

    # --- FEFO stock sufficiency (priority 11) — check all before mutating ---
    # Aggregate demand per product across lines (each line checked against eligible).
    demand_by_product = {}
    for (line, product, up, ext, pid) in priced:
        demand = line["weight_milli"] if product["sell_by_weight"] else line["quantity"]
        demand_by_product.setdefault(product["id"], 0)
        demand_by_product[product["id"]] += demand
    for product_id, demand in demand_by_product.items():
        if fefo_available(product_id) < demand:
            raise ApiError(ERR_INSUFFICIENT_STOCK[0], ERR_INSUFFICIENT_STOCK[1], "insufficient FEFO-eligible stock")

    # --- Commit: set line fields ---
    for (line, product, unit_price, extended, promo_id) in priced:
        line["unit_price_applied_cents"] = unit_price
        line["extended_price_cents"] = extended
        line["promo_id_applied"] = promo_id
        touch(line)

    total = max(0, subtotal - coupon_discount)

    # --- FEFO depletion accumulating cogs ---
    cogs = 0
    affected = {}
    for (line, product, up, ext, pid) in priced:
        demand = line["weight_milli"] if product["sell_by_weight"] else line["quantity"]
        cogs += fefo_deplete(product, demand)
        affected[product["id"]] = product
    for product in affected.values():
        product_inventory_rollup(product)
        touch(product)

    # --- Loyalty accrual (member tier at start of finalize) ---
    points_earned = 0
    if member is not None:
        base_points = total // 100
        tier = member["tier"]
        if tier == "GOLD":
            points_earned = (base_points * 20000) // 10000
        elif tier == "SILVER":
            points_earned = (base_points * 15000) // 10000
        else:
            points_earned = base_points
        member["points_balance"] += points_earned
        member["lifetime_spend_cents"] += total
        recompute_tier(member)
        touch(member)

    # --- Coupon redemption ---
    if clip is not None:
        clip["status"] = "REDEEMED"
        clip["redeemed_in_sale_id"] = sid
        touch(clip)

    # --- Persist computed totals on sale ---
    s["subtotal_cents"] = subtotal
    s["coupon_discount_cents"] = coupon_discount
    s["total_cents"] = total
    s["cogs_cents"] = cogs
    s["points_earned"] = points_earned
    s["clipped_coupon_id"] = clipped_coupon_id
    s["fulfillment_status"] = "FINALIZED"
    s["_finalized_at"] = now
    touch(s)
    return success(ser_sale(s))


@bp.route("/sales/<sid>/void", methods=["POST"])
def void_sale(sid):
    require_role("Cashier", "StoreManager")
    s = get_sale(sid)
    if s["fulfillment_status"] != "OPEN":
        raise ApiError(ERR_SALE_NOT_OPEN[0], ERR_SALE_NOT_OPEN[1], "sale not open")
    s["fulfillment_status"] = "VOIDED"
    touch(s)
    return success(ser_sale(s))


@bp.route("/sales/<sid>/pay", methods=["POST"])
def pay_sale(sid):
    require_role("Cashier", "StoreManager")
    s = get_sale(sid)
    # state ordering per scaffold: tender UNPAID first, then fulfillment FINALIZED
    if s["tender_status"] != "UNPAID":
        raise ApiError(ERR_SALE_NOT_UNPAID[0], ERR_SALE_NOT_UNPAID[1], "sale not unpaid")
    if s["fulfillment_status"] != "FINALIZED":
        raise ApiError(ERR_SALE_NOT_FINALIZED[0], ERR_SALE_NOT_FINALIZED[1], "sale not finalized")
    s["tender_status"] = "PAID"
    touch(s)
    return success(ser_sale(s))


@bp.route("/sales/<sid>/refund", methods=["POST"])
def refund_sale(sid):
    require_role("StoreManager")
    s = get_sale(sid)
    if s["tender_status"] != "PAID":
        raise ApiError(ERR_SALE_NOT_PAID[0], ERR_SALE_NOT_PAID[1], "sale not paid")

    # Compensation: restock depleted lots in reverse FEFO order.
    lines = _lines_of(sid)
    affected = {}
    for line in lines:
        product = db.products.get(line["product_id"])
        demand = line["weight_milli"] if product["sell_by_weight"] else line["quantity"]
        _restock(product, demand)
        affected[product["id"]] = product
    for product in affected.values():
        product_inventory_rollup(product)
        touch(product)

    # Revert coupon clip
    if s.get("clipped_coupon_id"):
        clip = db.clipped_coupons.get(s["clipped_coupon_id"])
        if clip is not None and clip["status"] == "REDEEMED" and clip.get("redeemed_in_sale_id") == sid:
            clip["status"] = "CLIPPED"
            clip["redeemed_in_sale_id"] = None
            touch(clip)

    # Reverse loyalty
    if s.get("member_id"):
        member = db.members.get(s["member_id"])
        if member is not None:
            member["points_balance"] = max(0, member["points_balance"] - s["points_earned"])
            member["lifetime_spend_cents"] -= s["total_cents"]
            if member["lifetime_spend_cents"] < 0:
                member["lifetime_spend_cents"] = 0
            recompute_tier(member)
            touch(member)

    s["tender_status"] = "REFUNDED"
    touch(s)
    return success(ser_sale(s))


def _restock(product, demand):
    """Restock `demand` units onto the SAME lots the sale depleted, in reverse
    FEFO order: refill the lots that were depleted latest first, up to received_qty.
    Lots restored from DEPLETED to ACTIVE as needed."""
    lots = [l for l in db.inventory_lots.values() if l["product_id"] == product["id"]]
    # reverse FEFO: FEFO order is expiration ASC (nulls last) then created_at ASC.
    # Reverse FEFO walks the FEFO order backwards so the lot consumed last is
    # refilled first.
    now = clock.now()

    def fefo_key(l):
        exp = l.get("_expiration_dt")
        null_tag = 1 if exp is None else 0
        return (null_tag, exp if exp is not None else now, l["created_at"], l.get("_seq", 0))

    lots.sort(key=fefo_key, reverse=True)
    remaining = demand
    for lot in lots:
        if remaining <= 0:
            break
        if lot["status"] not in ("ACTIVE", "DEPLETED"):
            continue
        capacity = lot["received_qty"] - lot["remaining_qty"]
        if capacity <= 0:
            continue
        give = min(capacity, remaining)
        lot["remaining_qty"] += give
        remaining -= give
        if lot["status"] == "DEPLETED" and lot["remaining_qty"] > 0:
            lot["status"] = "ACTIVE"
        touch(lot)
