"""Ticket tiers, the on-sale gate, sales with roll-up allocation, refunds
(PRD 3.4)."""

from flask import Blueprint, request

import store
from domain import allocate_tickets, recompute_show_ticket_counters, refund_sale
from envelope import created, ok
from errors import (already_terminal, biz, invalid_state, not_found,
                    stale_version)
from helpers import (body, filter_eq, get_child, get_show, list_response,
                     lookup, req_expected_show_version, req_int, req_str,
                     require_roles, ser_sale, ser_show, ser_tier)

bp = Blueprint("ticketing", __name__)

TIER_READ = ("VenueManager", "BookingAgent", "Promoter")
SALE_READ = ("VenueManager", "Promoter", "Accountant")
SHOW_TERMINAL = {"SETTLED", "CANCELLED"}


def _show_terminal_check(show):
    if show["status"] in SHOW_TERMINAL:
        raise already_terminal("Show is already in a terminal state")


# ---------------------------------------------------------------------------
# Ticket tiers
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/ticket-tiers")
def create_tier(sid):
    require_roles("Promoter")
    show = get_show(sid)
    b = body()
    name = req_str(b, "tier_name")
    price = req_int(b, "face_price_cents")
    capacity = req_int(b, "capacity")
    order = req_int(b, "tier_order")
    if price <= 0:
        from errors import invalid_request
        raise invalid_request("face_price_cents must be strictly positive")
    if capacity <= 0:
        from errors import invalid_request
        raise invalid_request("capacity must be strictly positive")
    # Rule 12: capacity budget + unique tier_order per show
    existing = [t for t in store.ticket_tiers.values() if t["show_id"] == show["id"]]
    if sum(t["capacity"] for t in existing) + capacity > show["total_capacity"]:
        raise biz("ERR_TIER_CAPACITY_EXCEEDED",
                  "Sum of tier capacities exceeds the show's total capacity")
    if any(t["tier_order"] == order for t in existing):
        raise biz("ERR_TIER_CAPACITY_EXCEEDED", "tier_order must be unique within the show")
    t = store.new_common({
        "show_id": show["id"],
        "tier_name": name,
        "face_price_cents": price,
        "capacity": capacity,
        "sold_count": 0,
        "refund_count": 0,
        "tier_order": order,
    })
    store.ticket_tiers[t["id"]] = t
    return created(ser_tier(t))


@bp.get("/shows/<sid>/ticket-tiers")
def list_tiers(sid):
    require_roles(*TIER_READ)
    show = get_show(sid)
    items = [t for t in store.ticket_tiers.values() if t["show_id"] == show["id"]]
    return list_response(items, ser_tier)


@bp.get("/shows/<sid>/ticket-tiers/<tid>")
def get_tier(sid, tid):
    require_roles(*TIER_READ)
    show = get_show(sid)
    return ok(ser_tier(get_child(store.ticket_tiers, show, tid, "TicketTier")))


# ---------------------------------------------------------------------------
# On-sale gate (CONFIRMED -> ON_SALE; OCC on Show.version)
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/on-sale")
def on_sale(sid):
    require_roles("Promoter")
    show = get_show(sid)
    if show["status"] != "CONFIRMED":
        _show_terminal_check(show)
        raise invalid_state("Only a CONFIRMED show can go on sale")
    if not show.get("deal_id"):
        raise invalid_state("Show has no accepted deal")
    tiers = [t for t in store.ticket_tiers.values() if t["show_id"] == show["id"]]
    if not tiers:
        raise invalid_state("At least one ticket tier must exist before going on sale")
    # OCC (rule 6) precedes the deposit-clearance gate (rule 8)
    expected = req_expected_show_version(body())
    if expected != show["version"]:
        raise stale_version()
    if show["deposit_paid_cents"] < show["deposit_required_cents"]:
        raise biz("ERR_DEPOSIT_NOT_CLEARED", "Artist deposit has not fully cleared")
    if store.now() < show["on_sale_at_utc"]:
        raise biz("ERR_DEPOSIT_NOT_CLEARED", "The public on-sale time has not been reached")
    show["status"] = "ON_SALE"
    store.bump_show(show)
    return ok(ser_show(show))


# ---------------------------------------------------------------------------
# Ticket sales
# ---------------------------------------------------------------------------
@bp.get("/ticket-sales/<sid>")
def get_sale_top(sid):
    require_roles(*SALE_READ)
    return ok(ser_sale(lookup(store.ticket_sales, sid, "TicketSale")))


@bp.get("/ticket-sales")
def list_sales_top():
    require_roles(*SALE_READ)
    items = list(store.ticket_sales.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "tier_id", request.args.get("tier_id"))
    items = filter_eq(items, "refund_status", request.args.get("refund_status"))
    return list_response(items, ser_sale)


@bp.post("/shows/<sid>/ticket-sales")
def create_sale(sid):
    require_roles("Promoter")
    show = get_show(sid)
    b = body()
    tier_id = req_str(b, "tier_id")
    quantity = req_int(b, "quantity", minimum=1)
    tier = store.ticket_tiers.get(tier_id)
    if tier is None or tier["show_id"] != show["id"]:
        raise not_found("TicketTier not found")
    if show["status"] not in ("ON_SALE", "ADVANCED", "SHOW_NIGHT"):
        _show_terminal_check(show)
        raise invalid_state("Ticket sales are accepted only once the show is on sale")
    allocations, gross = allocate_tickets(show, tier, quantity)
    sale = store.new_ledger({
        "show_id": show["id"],
        "tier_id": tier["id"],
        "quantity": quantity,
        "gross_amount_cents": gross,
        "sold_at_utc": store.mint_stamp(),
        "refund_status": "NONE",
        "_alloc": {t["id"]: take for t, take in allocations},
    })
    store.ticket_sales[sale["id"]] = sale
    for t, take in allocations:
        t["sold_count"] += take
        store.touch(t)
    recompute_show_ticket_counters(show)
    store.bump_show(show)
    return created(ser_sale(sale))


@bp.get("/shows/<sid>/ticket-sales")
def list_sales(sid):
    require_roles(*SALE_READ)
    show = get_show(sid)
    items = [s for s in store.ticket_sales.values() if s["show_id"] == show["id"]]
    items = filter_eq(items, "tier_id", request.args.get("tier_id"))
    items = filter_eq(items, "refund_status", request.args.get("refund_status"))
    return list_response(items, ser_sale)


@bp.get("/shows/<sid>/ticket-sales/<sale_id>")
def get_sale(sid, sale_id):
    require_roles(*SALE_READ)
    show = get_show(sid)
    return ok(ser_sale(get_child(store.ticket_sales, show, sale_id, "TicketSale")))


@bp.post("/shows/<sid>/ticket-sales/<sale_id>/refund")
def refund(sid, sale_id):
    require_roles("Promoter")
    show = get_show(sid)
    sale = get_child(store.ticket_sales, show, sale_id, "TicketSale")
    if sale["refund_status"] != "NONE":
        raise invalid_state("TicketSale has already been refunded")
    refund_sale(show, sale)
    return ok(ser_sale(sale))
