"""Routes: recurring routes, orders and their full lifecycle."""
from datetime import timedelta

import core
import domain
from core import (ALL_ROLES, agent_owns, as_enum, as_int, as_str,
                  authenticate, authorize, check_line_quantities, fail,
                  get_body, need, ok, paginate, parse_date_str, parse_lines,
                  parse_time_str, reject_unknown)
from server import app, fetch, new_record
from store import CUSTOMERS, DEPOTS, ENTRIES, ORDER_LINES, ORDERS, ROUTES, SLOTS
from views import entry_view, hold_view, line_view, order_view, route_view

ROUTE_READ_ROLES = {"PlatformAdmin", "DepotManager", "CustomerAgent"}
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


def fetch_order(order_id):
    return fetch(ORDERS, order_id, "Order")


def order_terminal_guard(o):
    if o["fulfillment_status"] == "CANCELLED":
        fail("ERR_ALREADY_TERMINAL", 409, "Order is CANCELLED")


# ---------------------------------------------------------------------------
# Recurring routes
# ---------------------------------------------------------------------------
def route_conflict(customer_id, weekday, exclude_id=None):
    for r in ROUTES.values():
        if r["id"] == exclude_id:
            continue
        if (r["customer_id"] == customer_id and r["weekday"] == weekday
                and r["status"] in ("ACTIVE", "PAUSED")):
            return True
    return False


@app.route("/recurring-routes", methods=["POST"])
def create_route():
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    data = get_body()
    # Rung 2 ownership (customer_id carried in the body)
    if "customer_id" in data and data["customer_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "CustomerAgent may only act for their own account")
    reject_unknown(data, {"customer_id", "depot_id", "weekday", "window_start",
                          "window_end", "standing_lines"})
    cid = as_str(need(data, "customer_id"), "customer_id")
    depot_id = as_str(need(data, "depot_id"), "depot_id")
    weekday = as_enum(need(data, "weekday"), "weekday", WEEKDAYS)
    ws = parse_time_str(need(data, "window_start"), "window_start")
    we = parse_time_str(need(data, "window_end"), "window_end")
    if ws >= we:
        fail("ERR_INVALID_REQUEST", 400, "window_start must be before window_end")
    lines = parse_lines(data, "standing_lines")
    fetch(CUSTOMERS, cid, "Customer")   # rung 5: body FK existence
    fetch(DEPOTS, depot_id, "Depot")
    check_line_quantities(lines)        # priority 16
    if route_conflict(cid, weekday):    # priority 20
        fail("ERR_ROUTE_SCHEDULE_CONFLICT", 409,
             "Another route for this customer and weekday is ACTIVE or PAUSED")
    r = new_record()
    r.update({"customer_id": cid, "depot_id": depot_id, "weekday": weekday,
              "window_start": ws, "window_end": we, "standing_lines": lines,
              "status": "ACTIVE", "last_generated_date": None})
    ROUTES[r["id"]] = r
    return ok(route_view(r), 201)


@app.route("/recurring-routes/<route_id>", methods=["GET"])
def get_route(route_id):
    uid, role = authenticate()
    authorize(role, ROUTE_READ_ROLES)
    r = fetch(ROUTES, route_id, "RecurringRoute")
    agent_owns(uid, role, r["customer_id"])
    return ok(route_view(r))


@app.route("/customers/<customer_id>/routes", methods=["GET"])
def list_customer_routes(customer_id):
    uid, role = authenticate()
    authorize(role, ROUTE_READ_ROLES)
    c = fetch(CUSTOMERS, customer_id, "Customer")
    agent_owns(uid, role, c["id"])
    items = sorted((r for r in ROUTES.values() if r["customer_id"] == customer_id),
                   key=lambda r: r["_seq"])
    status = core.request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, route_view)


@app.route("/depots/<depot_id>/routes", methods=["GET"])
def list_depot_routes(depot_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "DepotManager", "Dispatcher"})
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((r for r in ROUTES.values() if r["depot_id"] == depot_id),
                   key=lambda r: r["_seq"])
    status = core.request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, route_view)


@app.route("/recurring-routes/<route_id>/standing-order", methods=["PATCH"])
def patch_standing_order(route_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    data = get_body()
    reject_unknown(data, {"standing_lines", "expected_route_version"})
    lines = parse_lines(data, "standing_lines")
    expected = need(data, "expected_route_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", 400,
             "Field 'expected_route_version' must be an integer")
    r = fetch(ROUTES, route_id, "RecurringRoute")
    agent_owns(uid, role, r["customer_id"])
    # Rung 6: OCC before terminal/required-state guards (PRD §2.6)
    if expected != r["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_route_version does not match")
    if r["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "Route is TERMINATED")
    if r["status"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_INVALID_STATE", 409, "Standing order can only be patched from ACTIVE or PAUSED")
    check_line_quantities(lines)        # priority 16
    r["standing_lines"] = lines
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(route_view(r))


@app.route("/recurring-routes/<route_id>/pause", methods=["POST"])
def pause_route(route_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    r = fetch(ROUTES, route_id, "RecurringRoute")
    agent_owns(uid, role, r["customer_id"])
    if r["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "Route is TERMINATED")
    if r["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "Only an ACTIVE route can be paused")
    r["status"] = "PAUSED"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(route_view(r))


@app.route("/recurring-routes/<route_id>/resume", methods=["POST"])
def resume_route(route_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    r = fetch(ROUTES, route_id, "RecurringRoute")
    agent_owns(uid, role, r["customer_id"])
    if r["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "Route is TERMINATED")
    if r["status"] != "PAUSED":
        fail("ERR_INVALID_STATE", 409, "Only a PAUSED route can be resumed")
    if route_conflict(r["customer_id"], r["weekday"], exclude_id=r["id"]):
        fail("ERR_ROUTE_SCHEDULE_CONFLICT", 409,
             "Another route for this customer and weekday is ACTIVE or PAUSED")
    r["status"] = "ACTIVE"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(route_view(r))


@app.route("/recurring-routes/<route_id>/terminate", methods=["POST"])
def terminate_route(route_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    r = fetch(ROUTES, route_id, "RecurringRoute")
    agent_owns(uid, role, r["customer_id"])
    if r["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "Route is TERMINATED")
    if r["status"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_INVALID_STATE", 409, "Route cannot be terminated from this state")
    r["status"] = "TERMINATED"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(route_view(r))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    data = get_body()
    # Rung 2 ownership (customer_id carried in the body)
    if "customer_id" in data and data["customer_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "CustomerAgent may only act for their own account")
    reject_unknown(data, {"customer_id", "depot_id", "channel", "event_date",
                          "window_start", "window_end", "lines"})
    cid = as_str(need(data, "customer_id"), "customer_id")
    depot_id = as_str(need(data, "depot_id"), "depot_id")
    channel = as_enum(need(data, "channel"), "channel", {"DELIVERY", "WILL_CALL"})
    ev = parse_date_str(need(data, "event_date"), "event_date")
    ws = parse_time_str(need(data, "window_start"), "window_start")
    we = parse_time_str(need(data, "window_end"), "window_end")
    if ws >= we:
        fail("ERR_INVALID_REQUEST", 400, "window_start must be before window_end")
    lines = parse_lines(data, "lines")
    fetch(CUSTOMERS, cid, "Customer")   # rung 5: body FK existence
    fetch(DEPOTS, depot_id, "Depot")
    # Priority 11: lead-time check at creation
    if ev < core.today() + timedelta(days=1):
        fail("ERR_EVENT_TOO_SOON", 409,
             "event_date must be at least one day after the current logical date")
    check_line_quantities(lines)        # priority 16
    o = new_record()
    o.update({"customer_id": cid, "depot_id": depot_id, "recurring_route_id": None,
              "channel": channel, "event_date": ev, "window_start": ws,
              "window_end": we, "fulfillment_status": "DRAFT",
              "billing_status": "UNBILLED", "delivery_slot_id": None,
              "dispatch_run_id": None, "invoice_id": None,
              "price_book_id": None, "price_book_version": None,
              "pricing_mode": None, "merchandise_subtotal_cents": None,
              "discount_cents": None, "delivery_fee_cents": None,
              "surcharge_cents": None, "deposit_cents": None, "total_cents": None,
              "quoted_at": None, "confirmed_at": None, "fulfilled_at": None})
    ORDERS[o["id"]] = o
    for ln in lines:
        l = new_record()
        l.update({"order_id": o["id"], "product_form": ln["product_form"],
                  "packaging": ln["packaging"], "quantity_units": ln["quantity_units"],
                  "unit_weight_lbs": domain.WEIGHT_LBS[(ln["product_form"],
                                                        ln["packaging"])],
                  "unit_price_cents": None, "line_total_cents": None})
        ORDER_LINES[l["id"]] = l
    return ok(order_view(o), 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    return ok(order_view(o))


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    q = core.request.args
    items = sorted(ORDERS.values(), key=lambda o: o["_seq"])
    if role == "CustomerAgent":
        items = [o for o in items if o["customer_id"] == uid]
    for param in ("customer_id", "depot_id", "recurring_route_id",
                  "price_book_id", "delivery_slot_id"):
        val = q.get(param)
        if val is not None:
            items = [o for o in items if o[param] == val]
    status = q.get("status")
    if status is not None:
        items = [o for o in items if o["fulfillment_status"] == status]
    return paginate(items, order_view)


@app.route("/orders/<order_id>/quote", methods=["POST"])
def quote_order(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    order_terminal_guard(o)
    if o["fulfillment_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Only a DRAFT order can be quoted")
    book = domain.active_book()
    if book is None:
        fail("ERR_PRICE_BOOK_NOT_ACTIVE", 409, "No PriceBook is ACTIVE at quote time")
    apply = domain.compute_pricing(o, book)
    domain.apply_pricing(o, book, apply, "PROVISIONAL")
    o["price_book_id"] = book["id"]
    o["price_book_version"] = book["version"]
    o["fulfillment_status"] = "QUOTED"
    o["quoted_at"] = core.stamp()
    domain.touch_order(o)
    return ok(order_view(o))


@app.route("/orders/<order_id>/reprice", methods=["POST"])
def reprice_order(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    data = get_body()
    reject_unknown(data, {"expected_order_version"})
    expected = need(data, "expected_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", 400,
             "Field 'expected_order_version' must be an integer")
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    # Rung 6: OCC before terminal/required-state guards
    if expected != o["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_order_version does not match")
    order_terminal_guard(o)
    if o["fulfillment_status"] != "QUOTED":
        fail("ERR_INVALID_STATE", 409, "Only a QUOTED order can be repriced")
    book = domain.active_book()
    if book is None:
        fail("ERR_PRICE_BOOK_NOT_ACTIVE", 409, "No PriceBook is ACTIVE at reprice time")
    apply = domain.compute_pricing(o, book)
    domain.apply_pricing(o, book, apply, "PROVISIONAL")
    o["price_book_id"] = book["id"]
    o["price_book_version"] = book["version"]
    o["quoted_at"] = core.stamp()
    domain.touch_order(o)
    return ok(order_view(o))


@app.route("/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    order_terminal_guard(o)
    if o["fulfillment_status"] != "QUOTED":
        fail("ERR_INVALID_STATE", 409, "Only a QUOTED order can be confirmed")

    # Business gauntlet in the pinned order of PRD §3.5.
    pallets, dry = domain.order_measures(o["id"])
    we_dt = core.combine(o["event_date"], o["window_end"])
    # 1. dry-ice safety (priority 9)
    if dry > 0 and not domain.qualifying_cert(o["customer_id"], dry, we_dt):
        fail("ERR_DRY_ICE_CERT_REQUIRED", 409,
             "No qualifying ACTIVE handler certification for this dry-ice order")
    # 2. lead-time re-check (priority 11)
    if o["event_date"] < core.today() + timedelta(days=1):
        fail("ERR_EVENT_TOO_SOON", 409,
             "event_date is no longer at least one day beyond the logical date")
    # 3. DELIVERY implies a slot reservation
    if o["channel"] == "DELIVERY" and o["delivery_slot_id"] is None:
        fail("ERR_INVALID_STATE", 409,
             "A DELIVERY order must hold a slot reservation before confirm")
    depot = fetch(DEPOTS, o["depot_id"], "Depot")
    if domain.has_dry_ice(o["id"]):
        # 4. bunker exclusivity (priority 14)
        if domain.bunker_conflict(o):
            fail("ERR_HOLD_INTERVAL_CONFLICT", 409,
                 "Dry-ice bunker buffered interval conflicts with another hold")
    else:
        # 5. freezer peak-overlap (priority 19)
        if not domain.freezer_peak_ok(o, depot, pallets):
            fail("ERR_FREEZER_CAPACITY_EXCEEDED", 409,
                 "General-freezer peak overlap would exceed freezer capacity")
    # 6. surge admission (priority 21)
    covering = domain.covering_active_windows(o["depot_id"], o["event_date"])
    for w in covering:
        if w["admission_policy"] == "CLOSED":
            fail("ERR_SURGE_ADMISSION_CLOSED", 409,
                 "A covering surge window has admission_policy CLOSED")
    waitlist = False
    for w in covering:
        if w["admission_policy"] == "RATIONED":
            if domain.committed_pallets(o["depot_id"], o["event_date"]) + pallets \
                    > w["daily_pallet_cap"]:
                waitlist = True
    # 7-8. fiscal gates (priorities 26-27)
    cust = CUSTOMERS[o["customer_id"]]
    if domain.customer_standing(cust["id"]) != "GOOD":
        fail("ERR_CREDIT_HOLD", 402, "Customer standing is HOLD")
    book = domain.BOOKS[o["price_book_id"]]
    pricing = domain.compute_pricing(o, book)
    if domain.forward_exposure(cust["id"]) + pricing["total_cents"] > \
            cust["credit_limit_cents"] + cust["credit_balance_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED", 402,
             "Forward-looking exposure plus order total exceeds credit allowance")

    # Commit. The FINAL pricing computed above feeds the credit check either
    # way, but a waitlist-forked order keeps PROVISIONAL pricing, gets no
    # confirmed_at, and creates no hold (PRD §3.5).
    if waitlist:
        o["fulfillment_status"] = "WAITLISTED"
        domain.touch_order(o)
        domain.enqueue_waitlist(o)
    else:
        domain.apply_pricing(o, book, pricing, "FINAL")
        o["confirmed_at"] = core.stamp()
        o["fulfillment_status"] = "CONFIRMED"
        domain.touch_order(o)
        domain.create_hold(o)
    return ok(order_view(o))


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    order_terminal_guard(o)
    state = o["fulfillment_status"]
    if state not in ("DRAFT", "QUOTED", "CONFIRMED", "WAITLISTED"):
        fail("ERR_INVALID_STATE", 409,
             "Order cannot be cancelled from %s" % state)
    # The cancellation lands on CANCELLED first so the order leaves the
    # surge-committed set before the hold-release cascade triggers the
    # promotion sweep (PRD §3.6 hop 3 must not count this order).
    o["fulfillment_status"] = "CANCELLED"
    domain.touch_order(o)
    if state in ("QUOTED", "CONFIRMED", "WAITLISTED"):
        domain.release_slot_reservation(o)
    if state == "WAITLISTED":
        for e in ENTRIES.values():
            if e["order_id"] == o["id"] and e["status"] == "QUEUED":
                e["status"] = "WITHDRAWN"
    if state == "CONFIRMED":
        # Four-hop cascade: slot release (done) -> hold release -> posture
        # recompute -> promotion sweep on easing (inside release_hold).
        hold = domain.active_hold_for_order(o["id"])
        if hold is not None:
            domain.release_hold(hold, "RELEASED")
    return ok(order_view(o))


@app.route("/orders/<order_id>/reserve-slot", methods=["POST"])
def reserve_slot(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    data = get_body()
    reject_unknown(data, {"delivery_slot_id"})
    slot_id = as_str(need(data, "delivery_slot_id"), "delivery_slot_id")
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    slot = fetch(SLOTS, slot_id, "DeliverySlot")  # rung 5: body FK existence
    order_terminal_guard(o)
    if o["fulfillment_status"] != "QUOTED":
        fail("ERR_INVALID_STATE", 409, "Only a QUOTED order can reserve a slot")
    # State-category gauntlet (ERR_INVALID_STATE), in scaffold order
    if o["channel"] != "DELIVERY":
        fail("ERR_INVALID_STATE", 409, "WILL_CALL orders have no delivery slot")
    if o["delivery_slot_id"] is not None:
        fail("ERR_INVALID_STATE", 409,
             "Order already holds a reservation; cancel first to re-reserve")
    if slot["depot_id"] != o["depot_id"] or slot["date"] != o["event_date"]:
        fail("ERR_INVALID_STATE", 409, "Slot depot/date do not match the order")
    if domain.slot_status(slot) == "CLOSED":
        fail("ERR_INVALID_STATE", 409, "Slot is CLOSED")
    # Business checks in pinned order: containment (13), posture (17), capacity (18)
    if not (slot["window_start"] <= o["window_start"]
            and o["window_end"] <= slot["window_end"]):
        fail("ERR_WINDOW_OUTSIDE_SLOT", 409,
             "Order window is not contained in the slot window")
    if domain.depot_posture(DEPOTS[o["depot_id"]]) == "FROZEN":
        fail("ERR_POSTURE_FROZEN", 409,
             "Depot posture FROZEN blocks new slot reservations")
    pallets, _ = domain.order_measures(o["id"])
    if domain.slot_reserved_pallets(slot["id"]) + pallets > slot["capacity_pallets"]:
        fail("ERR_SLOT_CAPACITY_EXCEEDED", 409,
             "Slot reservation would exceed capacity_pallets")
    o["delivery_slot_id"] = slot["id"]
    domain.touch_order(o)
    domain.bump_slot(slot)
    return ok(order_view(o))


@app.route("/orders/<order_id>/stage", methods=["POST"])
def stage_order(order_id):
    uid, role = authenticate()
    authorize(role, {"DepotManager"})
    o = fetch_order(order_id)
    order_terminal_guard(o)
    if o["fulfillment_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", 409, "Only a CONFIRMED order can be staged")
    hold = domain.active_hold_for_order(o["id"])
    if hold is None or hold["status"] != "RESERVED":
        fail("ERR_INVALID_STATE", 409, "No RESERVED hold exists for this order")
    hold["status"] = "OCCUPIED"
    hold["version"] += 1
    hold["updated_at"] = core.stamp()
    o["fulfillment_status"] = "STAGED"
    domain.touch_order(o)
    return ok(order_view(o))


@app.route("/orders/<order_id>/mark-ready", methods=["POST"])
def mark_ready(order_id):
    uid, role = authenticate()
    authorize(role, {"DepotManager"})
    o = fetch_order(order_id)
    order_terminal_guard(o)
    if o["fulfillment_status"] != "STAGED":
        fail("ERR_INVALID_STATE", 409, "Only a STAGED order can be marked ready")
    if o["channel"] != "WILL_CALL":
        fail("ERR_INVALID_STATE", 409,
             "Only will-call orders can be marked ready for pickup")
    o["fulfillment_status"] = "READY_FOR_PICKUP"
    domain.touch_order(o)
    return ok(order_view(o))


@app.route("/orders/<order_id>/confirm-pickup", methods=["POST"])
def confirm_pickup(order_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    order_terminal_guard(o)
    if o["fulfillment_status"] != "READY_FOR_PICKUP":
        fail("ERR_INVALID_STATE", 409,
             "Only a READY_FOR_PICKUP order can be picked up")
    hold = domain.active_hold_for_order(o["id"]) or domain.latest_hold_for_order(o["id"])
    if hold is None:
        fail("ERR_INVALID_STATE", 409, "No cold-storage hold exists for this order")
    if core.now() > hold["interval_end"]:
        fail("ERR_PICKUP_WINDOW_EXPIRED", 409,
             "The pickup window has expired")
    o["fulfillment_status"] = "PICKED_UP"
    o["fulfilled_at"] = core.stamp()
    domain.touch_order(o)
    if hold["status"] == "OCCUPIED":
        domain.release_hold(hold, "RELEASED")
    return ok(order_view(o))


@app.route("/orders/<order_id>/lines", methods=["GET"])
def list_order_lines(order_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    return paginate(domain.order_lines(o["id"]), line_view)


@app.route("/orders/<order_id>/holds", methods=["GET"])
def list_order_holds(order_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    from store import HOLDS
    items = sorted((h for h in HOLDS.values() if h["order_id"] == o["id"]),
                   key=lambda h: h["_seq"])
    return paginate(items, hold_view)


@app.route("/orders/<order_id>/waitlist-entries", methods=["GET"])
def list_order_entries(order_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = fetch_order(order_id)
    agent_owns(uid, role, o["customer_id"])
    items = sorted((e for e in ENTRIES.values() if e["order_id"] == o["id"]),
                   key=lambda e: e["_seq"])
    return paginate(items, entry_view)
