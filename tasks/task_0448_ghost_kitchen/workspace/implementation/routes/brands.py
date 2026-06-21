"""VirtualBrand endpoints (PRD §3.2, §3.7 performance)."""
from flask import Blueprint

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from validation import get_body, require_str, require_int

bp = Blueprint("brands", __name__)


def _check_brand_owner(role, user_id, brand):
    """BrandOwner must own the brand (X-User-ID == VirtualBrand.id)."""
    if role == "BrandOwner" and user_id != brand["id"]:
        raise errors.forbidden()


@bp.route("/brands", methods=["POST"])
def create_brand():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    body = get_body()
    name = require_str(body, "name")
    owner_email = require_str(body, "owner_email")
    rate = require_int(body, "commission_rate_bps")
    if not (0 <= rate <= 5000):
        raise errors.invalid_request("commission_rate_bps must be in [0, 5000].")
    with store.lock:
        rec = new_entity("VirtualBrand", {
            "name": name,
            "owner_email": owner_email,
            "commission_rate_bps": rate,
            "availability": "PAUSED",
            "status": "ONBOARDING",
            "ledger_balance_cents": 0,
        })
        store.brands[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/brands/<bid>", methods=["GET"])
def get_brand(bid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        rec = get_or_404(store.brands, bid)
        return object_response(serialize(rec))


@bp.route("/brands", methods=["GET"])
def list_brands():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        items, limit, offset, total = paginate(list(store.brands.values()))
        return array_response(items, limit, offset, total)


@bp.route("/brands/<bid>/list", methods=["POST"])
def brand_list(bid):
    user_id, role = get_identity()
    require_role(role, ["BrandOwner"])
    with store.lock:
        rec = get_or_404(store.brands, bid)
        _check_brand_owner(role, user_id, rec)
        # PAUSED->LISTED requires availability PAUSED and status ACTIVE.
        if rec["availability"] != "PAUSED" or rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        rec["availability"] = "LISTED"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/brands/<bid>/pause", methods=["POST"])
def brand_pause(bid):
    user_id, role = get_identity()
    require_role(role, ["BrandOwner"])
    with store.lock:
        rec = get_or_404(store.brands, bid)
        _check_brand_owner(role, user_id, rec)
        # LISTED->PAUSED requires only availability LISTED.
        if rec["availability"] != "LISTED":
            raise errors.invalid_state()
        rec["availability"] = "PAUSED"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/brands/<bid>/deactivate", methods=["POST"])
def brand_deactivate(bid):
    user_id, role = get_identity()
    require_role(role, ["BrandOwner"])
    with store.lock:
        rec = get_or_404(store.brands, bid)
        _check_brand_owner(role, user_id, rec)
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        # No in-flight order (ROUTED or PREPARING) for this brand.
        for o in store.orders.values():
            if o["brand_id"] == bid and o["status"] in ("ROUTED", "PREPARING"):
                raise errors.invalid_state()
        rec["status"] = "DEACTIVATED"
        rec["availability"] = "PAUSED"
        # Cascade: every ACTIVE lease for this brand -> TERMINATED.
        for lease in store.leases.values():
            if lease["brand_id"] == bid and lease["status"] == "ACTIVE":
                lease["status"] = "TERMINATED"
                touch(lease)
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/brands/<bid>/menu-items", methods=["GET"])
def list_brand_menu_items(bid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        get_or_404(store.brands, bid)
        recs = [m for m in store.menu_items.values() if m["brand_id"] == bid]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)


@bp.route("/brands/<bid>/performance", methods=["GET"])
def brand_performance(bid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner"])
    with store.lock:
        rec = get_or_404(store.brands, bid)
        # Performance summary: fulfilled order count + gross/commission/food-cost
        # totals + ledger balance, on top of the serialized brand object.
        fulfilled = [
            o for o in store.orders.values()
            if o["brand_id"] == bid and o["status"] == "FULFILLED"
        ]
        out = serialize(rec)
        out["fulfilled_order_count"] = len(fulfilled)
        out["gross_revenue_cents_total"] = sum(o["gross_revenue_cents"] for o in fulfilled)
        out["commission_cents_total"] = sum(o["commission_cents"] for o in fulfilled)
        out["food_cost_cents_total"] = sum(o["food_cost_cents"] for o in fulfilled)
        return object_response(out)
