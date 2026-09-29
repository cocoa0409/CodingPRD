"""Order capture, build pricing, commitment and the independent money axis."""

from flask import Blueprint

from apihttp import authenticate, created, get_body, ok, paginate, query_str
from apihttp import _bad
from calc import (
    accrue_provisional,
    apply_promotion,
    assemble_totals,
    cut_kitchen_tickets,
    derive_tier,
    enter_assembled,
    enter_ready,
    fefo_select,
    find_loyalty_account,
    find_menu_item,
    find_modifier_option,
    find_order,
    find_order_line,
    find_order_line_of,
    find_store,
    order_lines_of,
    overlapping_window_count,
    price_line,
    recompute_order_subtotal,
    select_promotion,
    settle_points,
    tickets_of_order,
)
from core import (
    CATERING_LEAD_MINUTES,
    CATERING_MIN_SUBTOTAL_CENTS,
    PREORDER_LEAD_MINUTES,
    base_record,
    clock_date_str,
    db,
    plus_minutes,
    sort_created,
    touch,
)
from errors import ApiError
from serialize import order_line_out, order_out

bp = Blueprint("orders", __name__)

CHANNELS = ("TOUCHSCREEN", "MOBILE_PREORDER", "CATERING")
TENDER_TYPES = ("CARD", "CASH", "APP_WALLET")
WINDOW_CHANNELS = ("MOBILE_PREORDER", "CATERING")


def own_check(order, user_id, role):
    """PRD 2.1: a Customer may only act on an order they own."""
    if role == "Customer" and order["loyalty_account_id"] != user_id:
        raise ApiError("ERR_ORDER_NOT_OWNED")


def check_window_shape(channel, start, end):
    if channel == "TOUCHSCREEN":
        if start is not None or end is not None:
            raise ApiError("ERR_PICKUP_WINDOW_NOT_ALLOWED")
        return
    if start is None or end is None:
        raise ApiError("ERR_PICKUP_WINDOW_REQUIRED")
    if end <= start:
        raise ApiError("ERR_PICKUP_WINDOW_INVALID")


@bp.post("/orders")
def create_order():
    authenticate(("StoreTerminal", "Customer"))
    body = get_body()
    store_id = body.string("store_id")
    channel = body.enum("channel", CHANNELS)
    loyalty_account_id = body.string("loyalty_account_id", required=False, default=None)
    pickup_window_start = body.datetime("pickup_window_start", required=False, default=None)
    pickup_window_end = body.datetime("pickup_window_end", required=False, default=None)
    store = find_store(store_id)
    if loyalty_account_id is not None:
        loyalty_account_id = find_loyalty_account(loyalty_account_id)["id"]
    check_window_shape(channel, pickup_window_start, pickup_window_end)
    rec = base_record()
    rec.update({
        "store_id": store["id"],
        "loyalty_account_id": loyalty_account_id,
        "channel": channel,
        "production_status": "DRAFT",
        "settlement_status": "UNPAID",
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
        "daypart_at_placement": None,
        "subtotal_gross_cents": 0,
        "promo_discount_cents": 0,
        "service_fee_cents": 0,
        "total_cents": 0,
        "applied_promotion_id": None,
        "points_provisional": 0,
        "points_final": None,
        "expected_ready_at": None,
        "placed_at": None,
        "ready_at": None,
        "rework_count": 0,
        "tender_type": None,
    })
    db.orders[rec["id"]] = rec
    return created(order_out(rec))


@bp.get("/orders/<order_id>")
def read_order(order_id):
    user_id, role = authenticate((
        "StoreTerminal", "Customer", "StoreManager", "ShiftLead", "KitchenAssociate", "ChainAdmin",
    ))
    order = find_order(order_id)
    own_check(order, user_id, role)
    return ok(order_out(order))


@bp.get("/orders")
def list_orders():
    authenticate(("StoreManager", "ShiftLead", "ChainAdmin", "StoreTerminal"))
    orders = list(db.orders.values())
    for field in ("store_id", "loyalty_account_id", "applied_promotion_id",
                  "production_status", "settlement_status", "channel"):
        value = query_str(field)
        if value is not None:
            orders = [o for o in orders if o[field] == value]
    return paginate(sort_created(orders), order_out)


def _parse_modifiers(body, item):
    """Body-shape validation of the modifiers array; options resolved later."""
    entries = []
    for raw in body.array("modifiers", required=False, default=[]):
        if not isinstance(raw, dict):
            _bad("Each modifiers entry must be an object.")
        option_id = raw.get("modifier_option_id")
        qty = raw.get("qty")
        if not isinstance(option_id, str) or not option_id:
            _bad("Each modifiers entry needs a modifier_option_id string.")
        if isinstance(qty, bool) or not isinstance(qty, int):
            _bad("Each modifiers entry needs an integer qty.")
        entries.append({"modifier_option_id": option_id, "qty": qty})
    return entries


@bp.post("/orders/<order_id>/lines")
def add_order_line(order_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    body = get_body()
    menu_item_id = body.string("menu_item_id")
    qty = body.integer("qty", minimum=1)
    entries = _parse_modifiers(body, None)
    order = find_order(order_id)
    item = find_menu_item(menu_item_id)
    for entry in entries:
        entry["_option"] = find_modifier_option(entry["modifier_option_id"])
    own_check(order, user_id, role)
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")
    store = db.stores[order["store_id"]]
    for entry in entries:
        if entry["_option"]["menu_item_id"] != item["id"]:
            raise ApiError("ERR_MODIFIER_NOT_FOR_ITEM")
    if store["current_daypart"] not in item["valid_dayparts"]:
        raise ApiError("ERR_MENU_ITEM_NOT_IN_DAYPART")
    if order["channel"] == "CATERING" and not item["is_catering_eligible"]:
        raise ApiError("ERR_ITEM_NOT_CATERING_ELIGIBLE")
    for entry in entries:
        if entry["qty"] < 1 or entry["qty"] > entry["_option"]["max_qty"]:
            raise ApiError("ERR_MODIFIER_LIMIT_EXCEEDED")
    unit_price, surcharge, line_gross = price_line(item, qty, entries)
    rec = base_record()
    rec.update({
        "order_id": order["id"],
        "menu_item_id": item["id"],
        "qty": qty,
        "modifiers": [
            {"modifier_option_id": e["modifier_option_id"], "qty": e["qty"]} for e in entries
        ],
        "station": item["station"],
        "unit_price_cents": unit_price,
        "premium_surcharge_cents": surcharge,
        "line_gross_cents": line_gross,
        "line_discount_cents": 0,
        "line_net_cents": 0,
        "fulfillment_batch_id": None,
        "reserved_qty": 0,
    })
    db.order_lines[rec["id"]] = rec
    recompute_order_subtotal(order)
    touch(order)
    return created(order_line_out(rec))


@bp.delete("/orders/<order_id>/lines/<line_id>")
def delete_order_line(order_id, line_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    order = find_order(order_id)
    line = find_order_line_of(order, line_id)
    own_check(order, user_id, role)
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")
    del db.order_lines[line["id"]]
    recompute_order_subtotal(order)
    touch(order)
    return "", 204


@bp.get("/order-lines/<line_id>")
def read_order_line(line_id):
    authenticate(("StoreTerminal", "Customer", "StoreManager", "ShiftLead", "KitchenAssociate"))
    return ok(order_line_out(find_order_line(line_id)))


@bp.get("/order-lines")
def list_order_lines():
    authenticate(("StoreTerminal", "Customer", "StoreManager", "ShiftLead", "KitchenAssociate"))
    lines = list(db.order_lines.values())
    for field in ("order_id", "menu_item_id", "fulfillment_batch_id"):
        value = query_str(field)
        if value is not None:
            lines = [l for l in lines if l[field] == value]
    return paginate(sort_created(lines), order_line_out)


# ---------------------------------------------------------------------------
# committing a draft (PRD 3.8)
# ---------------------------------------------------------------------------
def _par_baked_lines(lines):
    out = []
    for line in lines:
        item = db.menu_items[line["menu_item_id"]]
        if item["fulfillment_mode"] == "PAR_BAKED_CASE":
            out.append((line, item))
    return out


def allocate_batches(order, lines):
    """First-expiring-first-out allocation across every par-baked line.

    Raises ERR_BATCH_HOLD_EXPIRED immediately (it outranks every later gate);
    a pure shortfall is returned so the caller can report it in its own slot.
    """
    taken = {}
    assignments = []
    shortfall = False
    for line, item in _par_baked_lines(lines):
        candidates = []
        for batch in db.production_batches.values():
            if batch["store_id"] != order["store_id"]:
                continue
            if batch["menu_item_id"] != line["menu_item_id"]:
                continue
            if batch["status"] != "HOLDING":
                continue
            available = batch["remaining_qty"] - taken.get(batch["id"], 0)
            if available < line["qty"]:
                continue
            candidates.append(batch)
        fresh = [
            b for b in candidates
            if b["hold_expires_at"] is not None and b["hold_expires_at"] > db.clock
        ]
        if fresh:
            fresh.sort(key=lambda b: (b["hold_expires_at"], b["created_at"], b["_seq"]))
            chosen = fresh[0]
            taken[chosen["id"]] = taken.get(chosen["id"], 0) + line["qty"]
            assignments.append((line, chosen))
            continue
        if candidates:
            raise ApiError("ERR_BATCH_HOLD_EXPIRED")
        shortfall = True
    return assignments, shortfall


@bp.post("/orders/<order_id>/place")
def place_order(order_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    order = find_order(order_id)
    own_check(order, user_id, role)
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")
    lines = order_lines_of(order["id"])
    if not lines:
        raise ApiError("ERR_ORDER_EMPTY")
    store = db.stores[order["store_id"]]
    service_date = clock_date_str()
    plan_found = any(
        p["store_id"] == store["id"]
        and p["daypart"] == store["current_daypart"]
        and p["service_date"] == service_date
        and p["status"] in ("PUBLISHED", "LOCKED")
        for p in db.staffing_plans.values()
    )
    if not plan_found:
        raise ApiError("ERR_DAYPART_PLAN_NOT_PUBLISHED")
    assignments, shortfall = allocate_batches(order, lines)
    for line in lines:
        item = db.menu_items[line["menu_item_id"]]
        if store["current_daypart"] not in item["valid_dayparts"]:
            raise ApiError("ERR_MENU_ITEM_NOT_IN_DAYPART")
    if order["channel"] == "CATERING":
        for line in lines:
            if not db.menu_items[line["menu_item_id"]]["is_catering_eligible"]:
                raise ApiError("ERR_ITEM_NOT_CATERING_ELIGIBLE")
    check_window_shape(order["channel"], order["pickup_window_start"], order["pickup_window_end"])
    if order["channel"] in WINDOW_CHANNELS:
        lead = (
            PREORDER_LEAD_MINUTES if order["channel"] == "MOBILE_PREORDER"
            else CATERING_LEAD_MINUTES
        )
        if order["pickup_window_start"] < plus_minutes(db.clock, lead):
            raise ApiError("ERR_PREORDER_LEAD_TIME_TOO_SHORT")
        if order["pickup_window_end"] <= db.clock:
            raise ApiError("ERR_PICKUP_WINDOW_ELAPSED")
        if overlapping_window_count(order) >= store["pickup_slot_capacity"]:
            raise ApiError("ERR_PICKUP_WINDOW_FULL")
    if shortfall:
        raise ApiError("ERR_INSUFFICIENT_BATCH_QTY")
    recompute_order_subtotal(order)
    if order["channel"] == "CATERING" and order["subtotal_gross_cents"] < CATERING_MIN_SUBTOTAL_CENTS:
        raise ApiError("ERR_ORDER_MINIMUM_NOT_MET")

    order["placed_at"] = db.clock
    order["daypart_at_placement"] = store["current_daypart"]
    rule, per_line, discount = select_promotion(order, store, lines)
    apply_promotion(order, rule, per_line, discount)
    assemble_totals(order)
    order["production_status"] = "PLACED"
    for line, batch in assignments:
        line["fulfillment_batch_id"] = batch["id"]
        line["reserved_qty"] = line["qty"]
        batch["remaining_qty"] -= line["qty"]
        batch["reserved_qty"] += line["qty"]
        touch(batch)
    for line in lines:
        touch(line)
    if order["loyalty_account_id"] is not None:
        accrue_provisional(order, db.loyalty_accounts[order["loyalty_account_id"]])
    tickets = cut_kitchen_tickets(order)
    if tickets:
        order["expected_ready_at"] = max(t["promised_ready_at"] for t in tickets)
    else:
        order["expected_ready_at"] = order["placed_at"]
    touch(order)
    if not tickets:
        enter_assembled(order, store)
    return ok(order_out(order))


# ---------------------------------------------------------------------------
# the money axis (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/authorize")
def authorize_order(order_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    body = get_body()
    tender_type = body.enum("tender_type", TENDER_TYPES)
    order = find_order(order_id)
    own_check(order, user_id, role)
    if order["settlement_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_SETTLEMENT_STATE_INVALID")
    if order["production_status"] not in ("PLACED", "IN_PRODUCTION", "ASSEMBLED", "READY"):
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    order["settlement_status"] = "AUTHORIZED"
    order["tender_type"] = tender_type
    touch(order)
    return ok(order_out(order))


@bp.post("/orders/<order_id>/settle")
def settle_order(order_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    order = find_order(order_id)
    own_check(order, user_id, role)
    if order["settlement_status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_SETTLEMENT_STATE_INVALID")
    if order["production_status"] == "VOIDED":
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    order["settlement_status"] = "SETTLED"
    if order["loyalty_account_id"] is not None:
        settle_points(order, db.loyalty_accounts[order["loyalty_account_id"]])
    else:
        order["points_final"] = 0
    touch(order)
    return ok(order_out(order))


@bp.post("/orders/<order_id>/refund")
def refund_order(order_id):
    authenticate(("StoreManager", "ShiftLead"))
    body = get_body()
    body.string("reason", min_len=1)
    order = find_order(order_id)
    if order["settlement_status"] != "SETTLED":
        raise ApiError("ERR_ORDER_SETTLEMENT_STATE_INVALID")
    account = None
    if order["loyalty_account_id"] is not None:
        account = db.loyalty_accounts[order["loyalty_account_id"]]
        points_final = order["points_final"] or 0
        if account["points_balance"] - points_final < 0:
            raise ApiError("ERR_POINTS_BALANCE_NEGATIVE")
    order["settlement_status"] = "REFUNDED"
    if account is not None:
        points_final = order["points_final"] or 0
        account["points_balance"] -= points_final
        account["points_reversed_total"] += points_final
        touch(account)
    touch(order)
    return ok(order_out(order))


@bp.post("/orders/<order_id>/release")
def release_order(order_id):
    authenticate(("StoreTerminal", "StoreManager"))
    order = find_order(order_id)
    if order["production_status"] != "ASSEMBLED":
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    start = order["pickup_window_start"]
    if start is not None and db.clock < start:
        raise ApiError("ERR_PICKUP_WINDOW_NOT_OPEN")
    enter_ready(order, db.stores[order["store_id"]])
    return ok(order_out(order))


@bp.post("/orders/<order_id>/void")
def void_order(order_id):
    authenticate(("StoreTerminal", "ShiftLead"))
    body = get_body()
    body.string("reason", min_len=1)
    order = find_order(order_id)
    if order["production_status"] not in ("DRAFT", "PLACED", "IN_PRODUCTION", "ASSEMBLED"):
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    if order["settlement_status"] == "SETTLED":
        raise ApiError("ERR_ORDER_SETTLEMENT_STATE_INVALID")
    was_draft = order["production_status"] == "DRAFT"
    order["production_status"] = "VOIDED"
    if not was_draft:
        for ticket in tickets_of_order(order["id"]):
            if ticket["status"] in ("QUEUED", "IN_PROGRESS"):
                ticket["status"] = "VOIDED"
                touch(ticket)
        for line in order_lines_of(order["id"]):
            batch_id = line["fulfillment_batch_id"]
            if batch_id is None or line["reserved_qty"] <= 0:
                continue
            batch = db.production_batches.get(batch_id)
            if batch is None:
                continue
            qty = line["reserved_qty"]
            batch["remaining_qty"] += qty
            batch["reserved_qty"] -= qty
            line["reserved_qty"] = 0
            touch(line)
            touch(batch)
        if order["points_provisional"] > 0 and order["loyalty_account_id"] is not None:
            account = db.loyalty_accounts[order["loyalty_account_id"]]
            account["points_balance"] -= order["points_provisional"]
            account["points_reversed_total"] += order["points_provisional"]
            touch(account)
    if order["settlement_status"] == "AUTHORIZED":
        order["settlement_status"] = "RELEASED"
    touch(order)
    return ok(order_out(order))


@bp.post("/orders/<order_id>/pickup")
def pickup_order(order_id):
    user_id, role = authenticate(("StoreTerminal", "Customer"))
    order = find_order(order_id)
    own_check(order, user_id, role)
    if order["production_status"] != "READY":
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    if order["channel"] in WINDOW_CHANNELS:
        start = order["pickup_window_start"]
        end = order["pickup_window_end"]
        if start is not None and db.clock < start:
            raise ApiError("ERR_PICKUP_WINDOW_NOT_OPEN")
        if end is not None and db.clock >= end:
            raise ApiError("ERR_PICKUP_WINDOW_NOT_OPEN")
    order["production_status"] = "PICKED_UP"
    touch(order)
    return ok(order_out(order))
