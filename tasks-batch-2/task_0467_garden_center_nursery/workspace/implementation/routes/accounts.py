"""Account endpoints + account-scoped reverse lists."""
from flask import Blueprint, request

from db import db, base_versioned
from lookups import body, get_nursery, get_account
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from validation import req_str, req_enum, req_int_in_range, opt_int

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"RETAIL", "LANDSCAPER_B2B"}


def account_view(a):
    return {
        "id": a["id"],
        "nursery_id": a["nursery_id"],
        "account_type": a["account_type"],
        "display_name": a["display_name"],
        "ship_to_hardiness_zone": a["ship_to_hardiness_zone"],
        "credit_limit_cents": a["credit_limit_cents"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "status": a["status"],
        "lifetime_points": a["lifetime_points"],
        "loyalty_tier": a["loyalty_tier"],
        "points_balance": a["points_balance"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/nurseries/<nursery_id>/accounts")
@require_roles("SalesClerk")
def create_account(nursery_id):
    get_nursery(nursery_id)
    data = body()
    account_type = req_enum(data, "account_type", ACCOUNT_TYPES)
    display_name = req_str(data, "display_name")
    zone = req_int_in_range(data, "ship_to_hardiness_zone", 1, 13)
    credit_limit = opt_int(data, "credit_limit_cents", 0)
    if credit_limit < 0:
        from errors import err
        import errors as e
        err(e.ERR_INVALID_REQUEST, "credit_limit_cents must be >= 0")
    if account_type == "RETAIL":
        credit_limit = 0  # retail forced to 0 regardless of supplied value

    a = base_versioned()
    a.update({
        "nursery_id": nursery_id,
        "account_type": account_type,
        "display_name": display_name,
        "ship_to_hardiness_zone": zone,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
        "lifetime_points": 0,
        "loyalty_tier": "STANDARD",
        "points_balance": 0,
    })
    db.accounts[a["id"]] = a
    return created(account_view(a))


@bp.get("/nurseries/<nursery_id>/accounts")
@require_roles("SalesClerk", "InventoryManager")
def list_accounts(nursery_id):
    get_nursery(nursery_id)
    limit, offset = parse_pagination()
    acct_type = request.args.get("account_type")
    status = request.args.get("status")
    items = [a for a in db.accounts.values() if a["nursery_id"] == nursery_id]
    if acct_type is not None:
        items = [a for a in items if a["account_type"] == acct_type]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([account_view(a) for a in page], limit, offset, total)


@bp.get("/accounts/<account_id>")
@require_roles("SalesClerk", "InventoryManager")
def read_account(account_id):
    a = get_account(account_id)
    return ok(account_view(a))


@bp.get("/accounts/<account_id>/loyalty-events")
@require_roles("SalesClerk", "InventoryManager")
def list_account_loyalty_events(account_id):
    get_account(account_id)
    limit, offset = parse_pagination()
    from routes.loyalty_events import loyalty_event_view
    items = [e for e in db.loyalty_events.values()
             if e["account_id"] == account_id]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([loyalty_event_view(e) for e in page], limit, offset, total)


@bp.get("/accounts/<account_id>/orders")
@require_roles("SalesClerk", "InventoryManager")
def list_account_orders(account_id):
    get_account(account_id)
    limit, offset = parse_pagination()
    from routes.orders import order_view
    ff = request.args.get("fulfillment_status")
    ps = request.args.get("payment_status")
    items = [o for o in db.orders.values() if o["account_id"] == account_id]
    if ff is not None:
        items = [o for o in items if o["fulfillment_status"] == ff]
    if ps is not None:
        items = [o for o in items if o["payment_status"] == ps]
    items.sort(key=lambda o: o["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([order_view(o) for o in page], limit, offset, total)


@bp.get("/accounts/<account_id>/special-orders")
@require_roles("SalesClerk", "InventoryManager")
def list_account_special_orders(account_id):
    get_account(account_id)
    limit, offset = parse_pagination()
    from routes.special_orders import special_order_view
    status = request.args.get("status")
    items = [s for s in db.special_orders.values()
             if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([special_order_view(s) for s in page], limit, offset, total)
