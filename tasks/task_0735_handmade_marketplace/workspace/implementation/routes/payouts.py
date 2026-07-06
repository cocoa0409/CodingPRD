"""Payout endpoints — create with OCC, mark-paid with settled net, release-hold."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, stamp_common, touch, now
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_PAYOUT_NOT_FOUND, ERR_SHOP_NOT_FOUND,
    ERR_PAYOUT_NOT_ELIGIBLE, ERR_STALE_SHOP_VERSION, ERR_INVALID_STATE,
    ERR_PAYOUT_HAS_OPEN_CASE,
)
from helpers import get_json_body, require_field, parse_pagination, paginate, sort_by_created
from serializers import payout_view
from services import find_shop

bp = Blueprint("payouts", __name__)


def _sweep_orders(shop_id):
    """Return eligible orders sorted by created_at ASC (fallback _seq)."""
    orders = [o for o in store.orders.values()
              if o["shop_id"] == shop_id
              and o["fulfillment_status"] == "COMPLETED"
              and o.get("payout_id") is None]
    return sorted(orders, key=lambda r: (r["created_at"], r.get("_seq", 0)))


@bp.route("/seller/payouts", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    body = get_json_body()
    shop_id = require_field(body, "shop_id", str)
    if "expected_shop_version" not in body or body["expected_shop_version"] is None:
        raise_err(ERR_VALIDATION, "expected_shop_version required")
    exp = body["expected_shop_version"]
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise_err(ERR_VALIDATION, "expected_shop_version must be int")

    require_shop_owner(user_id, role, shop_id)
    shop = find_shop(shop_id)
    if shop is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")

    # §3.9: eligibility check precedes OCC.
    swept = _sweep_orders(shop_id)
    if not swept:
        raise_err(ERR_PAYOUT_NOT_ELIGIBLE, "no eligible orders")

    if exp != shop["version"]:
        raise_err(ERR_STALE_SHOP_VERSION, "expected_shop_version mismatch")

    # Compute payout monetary fields.
    gross = sum(o["order_total_cents"] for o in swept)
    fees = sum(o["order_fee_cents"] for o in swept)
    estimated_net = sum(o["order_net_cents"] for o in swept)

    rec = {
        "shop_id": shop_id,
        "status": "SCHEDULED",
        "order_count": len(swept),
        "gross_cents": gross,
        "fees_cents": fees,
        "estimated_net_cents": estimated_net,
        "settled_net_cents": None,
        "net_cents": estimated_net,
        "scheduled_at": now(),
        "paid_at": None,
    }
    stamp_common(rec)
    store.payouts[rec["id"]] = rec

    # Set payout_id on swept orders.
    for o in swept:
        o["payout_id"] = rec["id"]
        touch(o)

    # Increment shop.version.
    touch(shop)

    return success(payout_view(rec), status=201)


@bp.route("/seller/payouts/<pid>", methods=["GET"])
def fetch(pid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    p = store.payouts.get(pid)
    if p is None:
        raise_err(ERR_PAYOUT_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, p["shop_id"])
    return success(payout_view(p))


@bp.route("/seller/payouts", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    status = request.args.get("status")
    items = list(store.payouts.values())
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([payout_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/payouts/<pid>/mark-paid", methods=["POST"])
def mark_paid(pid):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    p = store.payouts.get(pid)
    if p is None:
        raise_err(ERR_PAYOUT_NOT_FOUND, "not found")
    # State: SCHEDULED. ON_HOLD or PAID -> ERR_INVALID_STATE.
    if p["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "payout not SCHEDULED")

    # Any swept order has_open_case -> ERR_PAYOUT_HAS_OPEN_CASE.
    swept_orders = [o for o in store.orders.values() if o.get("payout_id") == pid]
    if any(o.get("has_open_case") for o in swept_orders):
        raise_err(ERR_PAYOUT_HAS_OPEN_CASE, "swept order has open case")

    # Settled net: sort by created_at ASC, exclude open-case and REFUNDED orders.
    sorted_orders = sorted(swept_orders, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    settled = [o for o in sorted_orders
               if not o.get("has_open_case")
               and o["payment_status"] != "REFUNDED"]
    settled_net = sum(o["order_net_cents"] for o in settled)

    p["settled_net_cents"] = settled_net
    p["net_cents"] = settled_net
    p["status"] = "PAID"
    p["paid_at"] = now()
    touch(p)

    shop = store.shops.get(p["shop_id"])
    if shop is not None:
        shop["available_balance_cents"] -= settled_net
        shop["lifetime_fees_cents"] += p["fees_cents"]
        touch(shop)

    return success(payout_view(p))


@bp.route("/seller/payouts/<pid>/release-hold", methods=["POST"])
def release_hold(pid):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    p = store.payouts.get(pid)
    if p is None:
        raise_err(ERR_PAYOUT_NOT_FOUND, "not found")
    if p["status"] != "ON_HOLD":
        raise_err(ERR_INVALID_STATE, "payout not ON_HOLD")
    # No swept order may still have an open case.
    for o in store.orders.values():
        if o.get("payout_id") == pid and o.get("has_open_case"):
            raise_err(ERR_INVALID_STATE, "swept order still has open case")
    p["status"] = "SCHEDULED"
    touch(p)
    return success(payout_view(p))
