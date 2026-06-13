"""Order endpoints (PRD §3.4 pricing)."""
from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_enum, require_int, err,
)
from errors import ERR_INVALID_REQUEST
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from routes.fee_schedules import active_schedule_for_category, CATEGORIES
from services.entity import stamp_create
from services.order import compute_components, provisional_net
from services.ledger import post_ledger_entry, HOLD_PENDING
from services.seller import refresh_seller_derived

bp = Blueprint("orders", __name__)


@bp.post("/orders")
def create_order():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    body = get_json_body()
    require_fields(body, ["seller_id", "category", "gross_amount_cents"])
    require_enum(body["category"], CATEGORIES, "category")
    require_int(body["gross_amount_cents"], "gross_amount_cents", 1)
    seller = fetch(db.sellers, body["seller_id"])

    schedule = active_schedule_for_category(body["category"])
    if schedule is None:
        # No active schedule to price against (PRD §3.4 requires an active
        # schedule for the category).
        raise err(ERR_INVALID_REQUEST,
                  "No active fee schedule for the order category.")

    gross = body["gross_amount_cents"]
    commission, platform_fee, processing = compute_components(gross, schedule)
    net = provisional_net(gross, commission, platform_fee, processing)

    order = {
        "seller_id": seller["id"],
        "fee_schedule_id": schedule["id"],
        "category": body["category"],
        "gross_amount_cents": gross,
        "commission_cents": commission,
        "platform_fee_cents": platform_fee,
        "processing_fee_cents": processing,
        "net_earnings_cents": net,
        "settlement_status": "PENDING",
        "clawback_status": "NONE",
        "refunded_amount_cents": 0,
        "settled_at": db.now_iso(),
        "matured_at": None,
    }
    stamp_create(order)
    db.orders[order["id"]] = order

    # Post ORDER_PROCEEDS ledger entry (PENDING) for the provisional net.
    post_ledger_entry(
        seller_id=seller["id"],
        source_type="ORDER_PROCEEDS",
        source_id=order["id"],
        amount_cents=net,
        hold_state=HOLD_PENDING,
        memo="Order proceeds",
    )
    refresh_seller_derived(seller)
    return success(order, status=201)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    order = fetch(db.orders, order_id)
    ensure_seller_owns(role, user_id, order["seller_id"])
    return success(order)


@bp.get("/orders")
def list_orders():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.orders.values())
    if role == ROLE_SELLER:
        items = [o for o in items if o["seller_id"] == user_id]
    for key in ("seller_id", "fee_schedule_id", "settlement_status", "clawback_status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)
