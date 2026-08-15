"""Quote routes: issue, list, get, send, accept, decline, revise."""
from datetime import timedelta
from flask import Blueprint, request
from middleware import require_role
from errors import (
    err_invalid_state, err_invalid_input, err_stale_version,
    err_duplicate_active, err_quote_expired, err_customer_on_hold,
)
from db import store, new_id
from response import success_object, success_list
from serializers import quote_view
from services import calc
from services.lazy import bump, refresh_quote, recompute_standing
from routes.common import (
    get_json_body, get_shop_or_404, get_work_order_or_404, get_quote_or_404,
    get_pagination, paginate,
)

bp = Blueprint("quotes", __name__)


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes", methods=["POST"])
def issue_quote(shopId, woId):
    require_role("Estimator")
    shop = get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    expected = body.get("expected_work_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_input("expected_work_order_version is required and must be an integer")

    # State check: must be DIAGNOSED (first issue) or QUOTED (re-issue after revise)
    if wo["status"] not in ("DIAGNOSED", "QUOTED"):
        raise err_invalid_state("WorkOrder must be DIAGNOSED or QUOTED to issue a quote")

    # OCC check
    if expected != wo["version"]:
        raise err_stale_version()

    # Uniqueness: at most one ISSUED quote per work order
    for q in store.quotes.values():
        if q["work_order_id"] == woId and q["status"] == "ISSUED":
            raise err_duplicate_active("A live ISSUED quote already exists for this work order")

    motor = store.motors[wo["motor_id"]]
    test_records = [t for t in store.test_records.values() if t["work_order_id"] == woId]

    now = store.now()
    computed = calc.compute_quote(shop, motor, wo, test_records, now)

    quote = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "work_order_id": woId,
        "variant": computed["variant"],
        "rewind_labor_cents": computed["rewind_labor_cents"],
        "rewind_materials_cents": computed["rewind_materials_cents"],
        "shop_supplies_cents": computed["shop_supplies_cents"],
        "rush_premium_cents": computed["rush_premium_cents"],
        "rewind_total_cents": computed["rewind_total_cents"],
        "risk_pct": computed["risk_pct"],
        "risk_cost_cents": computed["risk_cost_cents"],
        "tco_total_cents": computed["tco_total_cents"],
        "recommendation": computed["recommendation"],
        "status": "ISSUED",
        "issued_at": now,
        "expires_at": now + timedelta(days=calc.QUOTE_VALID_DAYS),
    }
    store.quotes[quote["id"]] = quote
    wo["active_quote_id"] = quote["id"]
    wo["status"] = "QUOTED"
    bump(wo)
    return success_object(quote_view(quote), status=201)


def _list_quotes(wo_id_filter):
    items = list(store.quotes.values())
    if wo_id_filter is not None:
        items = [q for q in items if q["work_order_id"] == wo_id_filter]
    if request.args.get("status"):
        items = [q for q in items if q["status"] == request.args["status"]]
    items.sort(key=lambda q: q["created_at"])
    return items


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes", methods=["GET"])
def list_quotes(shopId, woId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    # apply lazy expiry to all quotes for this WO before listing
    for q in store.quotes.values():
        if q["work_order_id"] == woId:
            refresh_quote(q)
    limit, offset = get_pagination()
    items = _list_quotes(woId)
    page, total = paginate(items, limit, offset)
    return success_list([quote_view(q) for q in page], limit, offset, total)


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes/<quoteId>", methods=["GET"])
def get_quote(shopId, woId, quoteId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    q = get_quote_or_404(quoteId, woId)
    refresh_quote(q)
    return success_object(quote_view(q))


@bp.route("/shops/quotes", methods=["GET"])
def list_quotes_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    # apply lazy expiry globally
    for q in store.quotes.values():
        refresh_quote(q)
    limit, offset = get_pagination()
    items = _list_quotes(request.args.get("work_order_id"))
    page, total = paginate(items, limit, offset)
    return success_list([quote_view(q) for q in page], limit, offset, total)


@bp.route("/shops/quotes/<quoteId>", methods=["GET"])
def get_quote_flat(quoteId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    q = get_quote_or_404(quoteId)
    refresh_quote(q)
    return success_object(quote_view(q))


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes/<quoteId>/send", methods=["POST"])
def send_quote(shopId, woId, quoteId):
    require_role("Estimator")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    q = get_quote_or_404(quoteId, woId)
    refresh_quote(q)
    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to send")
    if wo.get("active_quote_id") != q["id"]:
        raise err_invalid_state("Quote is not the work order's active quote")
    if wo["status"] != "QUOTED":
        raise err_invalid_state("WorkOrder must be QUOTED to send")
    wo["status"] = "AWAITING_APPROVAL"
    bump(wo)
    return success_object(quote_view(q))


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes/<quoteId>/accept", methods=["POST"])
def accept_quote(shopId, woId, quoteId):
    require_role("Customer")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    q = get_quote_or_404(quoteId, woId)

    # Expiry check first (priority 6): at or after expires_at -> auto-EXPIRED + reject
    if q["status"] == "ISSUED" and q["expires_at"] is not None and store.now() >= q["expires_at"]:
        refresh_quote(q)  # transitions to EXPIRED + clears active_quote_id + AWAITING_APPROVAL->QUOTED
        raise err_quote_expired()

    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to accept")

    # Standing check (priority 7)
    customer = store.customers.get(wo["customer_id"])
    if customer:
        recompute_standing(customer["id"])
        if customer["standing"] == "HOLD":
            raise err_customer_on_hold()

    if wo["status"] != "AWAITING_APPROVAL":
        raise err_invalid_state("WorkOrder must be AWAITING_APPROVAL to accept")

    q["status"] = "ACCEPTED"
    bump(q)
    wo["status"] = "APPROVED"
    bump(wo)
    return success_object(quote_view(q))


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes/<quoteId>/decline", methods=["POST"])
def decline_quote(shopId, woId, quoteId):
    require_role("Customer")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    q = get_quote_or_404(quoteId, woId)
    refresh_quote(q)
    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to decline")
    q["status"] = "DECLINED"
    bump(q)
    wo["status"] = "DECLINED"
    wo["active_quote_id"] = None
    motor = store.motors[wo["motor_id"]]
    motor["custody"] = "WITH_CUSTOMER"
    bump(motor)
    bump(wo)
    return success_object(quote_view(q))


@bp.route("/shops/<shopId>/work-orders/<woId>/quotes/<quoteId>/revise", methods=["POST"])
def revise_quote(shopId, woId, quoteId):
    require_role("Estimator")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    q = get_quote_or_404(quoteId, woId)
    refresh_quote(q)
    if q["status"] != "ISSUED":
        raise err_invalid_state("Quote must be ISSUED to revise")
    q["status"] = "SUPERSEDED"
    bump(q)
    wo["active_quote_id"] = None
    if wo["status"] == "AWAITING_APPROVAL":
        wo["status"] = "QUOTED"
    bump(wo)
    return success_object(quote_view(q))
