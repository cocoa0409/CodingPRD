"""Cart lifecycle, lines, applications, auto-apply, pricing, lock/checkout
(PRD §3.6 - §3.11)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_identity, require_roles
from response import success, success_list, success_null
from services.carts import (
    applied_apps,
    check_cart_ownership,
    mark_stale,
    reserved_redemptions,
)
from services.common import (
    new_record,
    paginate,
    require_int,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.pricing import (
    cart_subtotal,
    prospective_discount,
    raw_discount_for,
    reprice_cart,
)
from services.redemption import (
    check_caps,
    coupon_cap,
    eligibility_ok,
    is_redeemable,
)

bp = Blueprint("carts", __name__)


def _get_cart_owned(cart_id):
    """Existence (404) then ownership (403). Returns (cart, user_id, role)."""
    user_id, role = get_identity()
    cart = db.carts.get(cart_id)
    if not cart:
        raise err("ERR_NOT_FOUND", "Cart not found")
    check_cart_ownership(cart, user_id, role)
    return cart, user_id, role


# --------------------------------------------------------------------- Cart CRUD
@bp.post("/carts")
@require_roles("Shopper", "MerchantAdmin")
def create_cart():
    with db.lock:
        user_id, role = get_identity()
        body = require_json_object(request.get_json(silent=True))
        customer_id = require_str(body, "customer_id")
        if customer_id not in db.customers:
            raise err("ERR_FK_NOT_FOUND", "customer_id does not reference a customer")
        if role == "Shopper" and customer_id != user_id:
            raise err("ERR_FORBIDDEN_ROLE", "Shopper may only create their own cart")
        rec = new_record(
            {
                "customer_id": customer_id,
                "subtotal_cents": 0,
                "total_discount_cents": 0,
                "total_cents": 0,
                "pricing_status": "UNPRICED",
                "checkout_status": "OPEN",
            }
        )
        db.carts[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/carts/<cart_id>")
@require_roles("Shopper", "MerchantAdmin")
def get_cart(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        return success(serialize(cart), 200)


@bp.get("/carts")
@require_roles("Shopper", "MerchantAdmin")
def list_carts():
    with db.lock:
        user_id, role = get_identity()
        limit, offset = paginate(request.args)
        customer_id = request.args.get("customer_id")
        checkout_status = request.args.get("checkout_status")
        items = list(db.carts.values())
        # A Shopper only sees their own carts.
        if role == "Shopper":
            items = [c for c in items if c["customer_id"] == user_id]
        if customer_id is not None:
            items = [c for c in items if c["customer_id"] == customer_id]
        if checkout_status is not None:
            items = [c for c in items if c["checkout_status"] == checkout_status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(c) for c in page], limit, offset, total)


# --------------------------------------------------------------------- CartLine
@bp.post("/carts/<cart_id>/lines")
@require_roles("Shopper", "MerchantAdmin")
def add_line(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        body = require_json_object(request.get_json(silent=True))
        sku = require_str(body, "sku")
        unit_price = require_int(body, "unit_price_cents", minimum=1)
        quantity = require_int(body, "quantity", minimum=1)
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        rec = new_record(
            {
                "cart_id": cart_id,
                "sku": sku,
                "unit_price_cents": unit_price,
                "quantity": quantity,
                "line_total_cents": unit_price * quantity,
            }
        )
        db.cart_lines[rec["id"]] = rec
        mark_stale(cart)
        return success(serialize(rec), 201)


@bp.get("/carts/<cart_id>/lines")
@require_roles("Shopper", "MerchantAdmin")
def list_lines(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        limit, offset = paginate(request.args)
        items = [l for l in db.cart_lines.values() if l["cart_id"] == cart_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(l) for l in page], limit, offset, total)


@bp.patch("/carts/<cart_id>/lines/<line_id>")
@require_roles("Shopper", "MerchantAdmin")
def update_line(cart_id, line_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        line = db.cart_lines.get(line_id)
        if not line or line["cart_id"] != cart_id:
            raise err("ERR_NOT_FOUND", "Cart line not found")
        body = require_json_object(request.get_json(silent=True))
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        if "unit_price_cents" in body and body["unit_price_cents"] is not None:
            up = body["unit_price_cents"]
            if isinstance(up, bool) or not isinstance(up, int) or up < 1:
                raise err("ERR_INVALID_REQUEST", "unit_price_cents must be a positive integer")
            line["unit_price_cents"] = up
        if "quantity" in body and body["quantity"] is not None:
            q = body["quantity"]
            if isinstance(q, bool) or not isinstance(q, int) or q < 1:
                raise err("ERR_INVALID_REQUEST", "quantity must be >= 1")
            line["quantity"] = q
        line["line_total_cents"] = line["unit_price_cents"] * line["quantity"]
        touch(line)
        mark_stale(cart)
        return success(serialize(line), 200)


@bp.delete("/carts/<cart_id>/lines/<line_id>")
@require_roles("Shopper", "MerchantAdmin")
def delete_line(cart_id, line_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        line = db.cart_lines.get(line_id)
        if not line or line["cart_id"] != cart_id:
            raise err("ERR_NOT_FOUND", "Cart line not found")
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        del db.cart_lines[line_id]
        mark_stale(cart)
        return success(serialize(line), 200)


# ----------------------------------------------------------------- Applications
def _exclusion_pair_exists(promo_a_id, promo_b_id):
    for r in db.exclusion_rules.values():
        pair = {r["promotion_a_id"], r["promotion_b_id"]}
        if pair == {promo_a_id, promo_b_id}:
            return True
    return False


def _check_stacking(cart_id, new_promo):
    """Stacking legality (priority 13)."""
    existing = applied_apps(cart_id)
    if not existing:
        return
    # EXCLUSIVE new promotion may not coexist with any other APPLIED application.
    if new_promo["stacking_class"] == "EXCLUSIVE":
        raise err("ERR_STACKING_CONFLICT", "EXCLUSIVE promotion cannot stack")
    # Any existing EXCLUSIVE application blocks adding another.
    for app in existing:
        ep = db.promotions[app["promotion_id"]]
        if ep["stacking_class"] == "EXCLUSIVE":
            raise err("ERR_STACKING_CONFLICT", "Existing EXCLUSIVE promotion present")
    # Two STACKABLE promotions joined by an exclusion edge conflict.
    for app in existing:
        if _exclusion_pair_exists(new_promo["id"], app["promotion_id"]):
            raise err("ERR_STACKING_CONFLICT", "Promotions are mutually exclusive")


@bp.post("/carts/<cart_id>/applications")
@require_roles("Shopper", "MerchantAdmin")
def apply_coupon(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        body = require_json_object(request.get_json(silent=True))
        code = require_str(body, "code")
        customer = db.customers[cart["customer_id"]]

        # Resolve coupon by code (case-insensitive).
        coupon = None
        for c in db.coupons.values():
            if c["code"].lower() == code.lower():
                coupon = c
                break
        if coupon is None:
            raise err("ERR_FK_NOT_FOUND", "code does not reference a coupon")
        promotion = db.promotions[coupon["promotion_id"]]

        # Priority 10: cart must be OPEN.
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")

        # Priority 11: redeemability. Coupon DISABLED first per §3.8 ordering.
        if coupon["status"] == "DISABLED":
            raise err("ERR_COUPON_DISABLED", "Coupon is disabled")
        # An EXHAUSTED promotion (budget fully consumed) is rejected with the
        # specific budget-exhausted error, not the generic not-redeemable one
        # (PRD §3.3 / §3.8: "if the budget is already fully consumed (the
        # promotion is EXHAUSTED) the application is rejected with
        # ERR_PROMO_BUDGET_EXHAUSTED").
        if promotion["status"] == "EXHAUSTED":
            raise err("ERR_PROMO_BUDGET_EXHAUSTED", "Promotion budget is exhausted")
        if not is_redeemable(promotion, db.clock):
            raise err("ERR_PROMO_NOT_REDEEMABLE", "Promotion is not redeemable")

        # Priority 12: eligibility.
        if not eligibility_ok(promotion, customer):
            raise err("ERR_NOT_ELIGIBLE", "Customer not eligible")

        # Priority 13: stacking legality.
        _check_stacking(cart_id, promotion)

        # Prospective discount for caps/headroom.
        new_discount = prospective_discount(promotion, cart_id)

        # Priorities 14-17: coupon cap, abuse limit, budget headroom.
        check_caps(promotion, coupon, customer, new_discount)

        # Priority 18: OCC on Promotion.version when promotion is budget-capped.
        if promotion["budget_cap_cents"] is not None:
            expected = body.get("expected_promotion_version")
            if expected is None or expected != promotion["version"]:
                raise err(
                    "ERR_STALE_PROMOTION_VERSION",
                    "expected_promotion_version mismatch",
                )

        rec = new_record(
            {
                "cart_id": cart_id,
                "promotion_id": promotion["id"],
                "coupon_id": coupon["id"],
                "source": "MANUAL",
                "raw_discount_cents": 0,
                "discount_cents": 0,
                "status": "APPLIED",
            }
        )
        db.cart_applications[rec["id"]] = rec
        mark_stale(cart)
        # Application records a provisional usage projection -> bump promo version.
        touch(promotion)
        return success(serialize(rec), 201)


@bp.get("/carts/<cart_id>/applications")
@require_roles("Shopper", "MerchantAdmin")
def list_cart_applications(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        limit, offset = paginate(request.args)
        status = request.args.get("status")
        items = [a for a in db.cart_applications.values() if a["cart_id"] == cart_id]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(a) for a in page], limit, offset, total)


@bp.delete("/carts/<cart_id>/applications/<application_id>")
@require_roles("Shopper", "MerchantAdmin")
def remove_application(cart_id, application_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        app = db.cart_applications.get(application_id)
        if not app or app["cart_id"] != cart_id:
            raise err("ERR_NOT_FOUND", "Application not found")
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        if app["status"] != "APPLIED":
            raise err("ERR_INVALID_STATE", "Application is not APPLIED")
        app["status"] = "REMOVED"
        touch(app)
        mark_stale(cart)
        return success(serialize(app), 200)


@bp.get("/cart-applications/<application_id>")
@require_roles("Shopper", "MerchantAdmin")
def get_cart_application(application_id):
    with db.lock:
        user_id, role = get_identity()
        app = db.cart_applications.get(application_id)
        if not app:
            raise err("ERR_NOT_FOUND", "Application not found")
        if role == "Shopper":
            cart = db.carts.get(app["cart_id"])
            if not cart or cart["customer_id"] != user_id:
                raise err("ERR_FORBIDDEN_ROLE", "Not the owning customer")
        return success(serialize(app), 200)


@bp.get("/cart-applications")
@require_roles("MerchantAdmin")
def list_global_applications():
    with db.lock:
        limit, offset = paginate(request.args)
        promotion_id = request.args.get("promotion_id")
        coupon_id = request.args.get("coupon_id")
        cart_id = request.args.get("cart_id")
        status = request.args.get("status")
        items = list(db.cart_applications.values())
        if promotion_id is not None:
            items = [a for a in items if a["promotion_id"] == promotion_id]
        if coupon_id is not None:
            items = [a for a in items if a["coupon_id"] == coupon_id]
        if cart_id is not None:
            items = [a for a in items if a["cart_id"] == cart_id]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(a) for a in page], limit, offset, total)


# ------------------------------------------------------------------- Auto-apply
@bp.post("/carts/<cart_id>/auto-apply")
@require_roles("Shopper", "MerchantAdmin")
def auto_apply(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        customer = db.customers[cart["customer_id"]]
        subtotal = cart_subtotal(cart_id)
        existing = applied_apps(cart_id)

        coupon_promo_ids = {c["promotion_id"] for c in db.coupons.values()}

        candidates = []
        for p in db.promotions.values():
            if not is_redeemable(p, db.clock):
                continue
            # Stacking applicability.
            if p["stacking_class"] == "EXCLUSIVE" and existing:
                continue
            if not eligibility_ok(p, customer):
                continue
            # Budget not exhausted.
            if p["budget_cap_cents"] is not None and not (
                p["budget_consumed_cents"] < p["budget_cap_cents"]
            ):
                continue
            # Public surface: a promotion with at least one coupon is gated out.
            if p["id"] in coupon_promo_ids:
                continue
            raw = raw_discount_for(p, cart_id, subtotal)
            candidates.append((raw, p["_seq"], p))

        if not candidates:
            # Empty candidate set -> no application, 200 with literal null data
            # (PRD §3.9: "a 200 response with null data").
            return success_null(200)

        # Rank: raw_discount DESC, then promotion created_at (seq) ASC.
        candidates.sort(key=lambda t: (-t[0], t[1]))
        best = candidates[0][2]

        rec = new_record(
            {
                "cart_id": cart_id,
                "promotion_id": best["id"],
                "coupon_id": None,
                "source": "AUTO_APPLY",
                "raw_discount_cents": 0,
                "discount_cents": 0,
                "status": "APPLIED",
            }
        )
        db.cart_applications[rec["id"]] = rec
        mark_stale(cart)
        touch(best)
        return success(serialize(rec), 201)


# --------------------------------------------------------------------- Pricing
@bp.post("/carts/<cart_id>/reprice")
@require_roles("Shopper", "MerchantAdmin")
def reprice(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_CART_NOT_OPEN", "Cart is not OPEN")
        reprice_cart(cart)
        cart["pricing_status"] = "PRICED"
        touch(cart)
        return success(serialize(cart), 200)


# --------------------------------------------------------------- Lock / Unlock
@bp.post("/carts/<cart_id>/lock")
@require_roles("Shopper", "MerchantAdmin")
def lock(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        if cart["checkout_status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Cart is not OPEN")
        # Cross-dimension guard (priority 10): pricing must be PRICED.
        if cart["pricing_status"] != "PRICED":
            raise err("ERR_CART_NOT_PRICED", "Cart is not PRICED")
        customer = db.customers[cart["customer_id"]]
        apps = applied_apps(cart_id)

        # Re-verify each application: redeemability then caps, in priority order.
        for app in apps:
            promo = db.promotions[app["promotion_id"]]
            if not is_redeemable(promo, db.clock):
                raise err("ERR_PROMO_NOT_REDEEMABLE", "Promotion is not redeemable")
        for app in apps:
            promo = db.promotions[app["promotion_id"]]
            coupon = db.coupons.get(app["coupon_id"]) if app["coupon_id"] else None
            check_caps(promo, coupon, customer, app["discount_cents"])

        # All preconditions pass -> create reservations atomically.
        for app in apps:
            rec = new_record(
                {
                    "coupon_id": app["coupon_id"],
                    "promotion_id": app["promotion_id"],
                    "customer_id": cart["customer_id"],
                    "cart_id": cart_id,
                    "discount_cents": app["discount_cents"],
                    "status": "RESERVED",
                }
            )
            db.coupon_redemptions[rec["id"]] = rec
        cart["checkout_status"] = "LOCKED"
        touch(cart)
        return success(serialize(cart), 200)


@bp.post("/carts/<cart_id>/unlock")
@require_roles("Shopper", "MerchantAdmin")
def unlock(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        if cart["checkout_status"] != "LOCKED":
            raise err("ERR_INVALID_STATE", "Cart is not LOCKED")
        for r in reserved_redemptions(cart_id):
            r["status"] = "RELEASED"
            touch(r)
        cart["checkout_status"] = "OPEN"
        touch(cart)
        return success(serialize(cart), 200)


# --------------------------------------------------------------------- Checkout
@bp.post("/carts/<cart_id>/checkout")
@require_roles("Shopper", "MerchantAdmin")
def checkout(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        body = require_json_object(request.get_json(silent=True))
        if "expected_cart_version" not in body or body["expected_cart_version"] is None:
            raise err("ERR_INVALID_REQUEST", "expected_cart_version required")
        if cart["checkout_status"] != "LOCKED":
            raise err("ERR_INVALID_STATE", "Cart is not LOCKED")
        # OCC (priority 18).
        if body["expected_cart_version"] != cart["version"]:
            raise err("ERR_STALE_CART_VERSION", "expected_cart_version mismatch")

        customer = db.customers[cart["customer_id"]]
        reserved = reserved_redemptions(cart_id)

        # Re-check each reserved redemption still within caps (vs CONFIRMED+RESERVED,
        # the redemption itself already counted -> count_self).
        for r in reserved:
            promo = db.promotions[r["promotion_id"]]
            coupon = db.coupons.get(r["coupon_id"]) if r["coupon_id"] else None
            check_caps(promo, coupon, customer, r["discount_cents"], count_self=r)

        # Settlement.
        for r in reserved:
            r["status"] = "CONFIRMED"
            touch(r)
            promo = db.promotions[r["promotion_id"]]
            promo["budget_consumed_cents"] += r["discount_cents"]
            touch(promo)
            if r["coupon_id"]:
                coupon = db.coupons[r["coupon_id"]]
                coupon["redeemed_count"] += 1
                touch(coupon)
                cap = coupon_cap(coupon)
                if coupon["redeemed_count"] >= cap:
                    coupon["status"] = "EXHAUSTED"
                    touch(coupon)
            # Promotion budget exhaustion auto-transition.
            if (
                promo["budget_cap_cents"] is not None
                and promo["budget_consumed_cents"] >= promo["budget_cap_cents"]
                and promo["status"] == "ACTIVE"
            ):
                promo["status"] = "EXHAUSTED"
                touch(promo)

        customer["order_count"] += 1
        customer["lifetime_discount_cents"] += cart["total_discount_cents"]
        touch(customer)

        cart["checkout_status"] = "CHECKED_OUT"
        touch(cart)
        return success(serialize(cart), 200)


@bp.post("/carts/<cart_id>/abandon")
@require_roles("Shopper", "MerchantAdmin")
def abandon(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        if cart["checkout_status"] not in ("OPEN", "LOCKED"):
            raise err("ERR_INVALID_STATE", "Cart cannot be abandoned from this state")
        if cart["checkout_status"] == "LOCKED":
            for r in reserved_redemptions(cart_id):
                r["status"] = "RELEASED"
                touch(r)
        for app in applied_apps(cart_id):
            app["status"] = "REMOVED"
            touch(app)
        cart["checkout_status"] = "ABANDONED"
        touch(cart)
        return success(serialize(cart), 200)


# ------------------------------------------------------------------ Redemptions
@bp.get("/carts/<cart_id>/redemptions")
@require_roles("Shopper", "MerchantAdmin")
def list_cart_redemptions(cart_id):
    with db.lock:
        cart, _, _ = _get_cart_owned(cart_id)
        limit, offset = paginate(request.args)
        status = request.args.get("status")
        items = [
            r for r in db.coupon_redemptions.values() if r["cart_id"] == cart_id
        ]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(r) for r in page], limit, offset, total)
