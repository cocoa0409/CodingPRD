"""Stadium Venue Concessions API — entry point and all routes.

Python + Flask. In-memory storage only (db.store). The store starts EMPTY on
every boot — nothing is seeded. Re-invoking start.sh (a fresh process) wipes all
state. Behaviors trace to PRD.md (the contract) and SCAFFOLD.yaml.
"""

import os

from flask import Flask, g, request

import errors
import serializers as S
import services
import util
from db import store
from middleware import require_auth
from response import object_response, array_response, error_response

app = Flask(__name__)

# All roles (used for shared read endpoints).
M = "ConcessionsManager"
R = "StockRunner"
O = "StandOperator"
P = "Patron"


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route -> treat as resource not found per envelope.
    return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    # Fall back to a malformed-request style error so the envelope is preserved.
    return error_response(errors.ERR_INVALID_REQUEST, f"Unexpected error: {exc}", 422)


# ===========================================================================
# Generic list helper
# ===========================================================================
def list_response(collection_values, serialize, predicate=None):
    items = [o for o in collection_values if (predicate is None or predicate(o))]
    items = util.sort_by_created(items)
    limit, offset = util.parse_pagination()
    page, total = util.paginate(items, limit, offset)
    data = [serialize(o) for o in page]
    return array_response(data, limit, offset, total)


# ===========================================================================
# Venue
# ===========================================================================
@app.route("/concessions/venues", methods=["POST"])
@require_auth([M])
def create_venue():
    body = util.get_json_body()
    name = util.as_nonempty_string(util.require_field(body, "name"), "name", max_len=120)
    venue_share_pct = util.as_pct(util.require_field(body, "venue_share_pct"), "venue_share_pct")
    service_fee_pct = util.as_pct(util.require_field(body, "service_fee_pct"), "service_fee_pct")
    share_basis = body.get("share_basis", "GROSS")
    util.as_enum(share_basis, "share_basis", {"GROSS", "NET"})
    spoilage_valuation = body.get("spoilage_valuation", "FIFO")
    util.as_enum(spoilage_valuation, "spoilage_valuation", {"FIFO", "WEIGHTED_AVG"})

    with store.lock:
        v = {
            "name": name,
            "venue_share_pct": venue_share_pct,
            "service_fee_pct": service_fee_pct,
            "share_basis": share_basis,
            "spoilage_valuation": spoilage_valuation,
        }
        util.stamp_create(v)
        store.venues[v["id"]] = v
    return object_response(S.venue(v), 201)


@app.route("/concessions/venues/<vid>", methods=["GET"])
@require_auth([M, R, O, P])
def get_venue(vid):
    v = util.lookup(store.venues, vid)
    return object_response(S.venue(v))


# ===========================================================================
# Product
# ===========================================================================
@app.route("/concessions/products", methods=["POST"])
@require_auth([M])
def create_product():
    body = util.get_json_body()
    venue_id = util.require_field(body, "venue_id")
    sku = util.as_nonempty_string(util.require_field(body, "sku"), "sku")
    name = util.as_nonempty_string(util.require_field(body, "name"), "name")
    base_price_cents = util.as_int(util.require_field(body, "base_price_cents"), "base_price_cents")
    unit_cost_cents = util.as_int(util.require_field(body, "unit_cost_cents"), "unit_cost_cents")
    perishable = body.get("perishable", False)
    util.as_bool(perishable, "perishable")
    if base_price_cents < 0:
        raise errors.invalid_request("base_price_cents must be >= 0.")
    if unit_cost_cents < 0:
        raise errors.invalid_request("unit_cost_cents must be >= 0.")

    with store.lock:
        # Existence of the referenced venue (priority 3).
        util.lookup(store.venues, venue_id)
        # Business: sku unique per (venue_id, sku). PRD §3.1.
        for pr in store.products.values():
            if pr["venue_id"] == venue_id and pr["sku"] == sku:
                raise errors.invalid_request("sku must be unique within the venue.")
        p = {
            "venue_id": venue_id,
            "sku": sku,
            "name": name,
            "base_price_cents": base_price_cents,
            "unit_cost_cents": unit_cost_cents,
            "perishable": perishable,
        }
        util.stamp_create(p)
        store.products[p["id"]] = p
    return object_response(S.product(p), 201)


@app.route("/concessions/products/<pid>", methods=["GET"])
@require_auth([M, R, O, P])
def get_product(pid):
    p = util.lookup(store.products, pid)
    return object_response(S.product(p))


@app.route("/concessions/products", methods=["GET"])
@require_auth([M, R, O, P])
def list_products():
    venue_id = request.args.get("venue_id")
    pred = (lambda o: o["venue_id"] == venue_id) if venue_id is not None else None
    return list_response(store.products.values(), S.product, pred)


# ===========================================================================
# Event
# ===========================================================================
@app.route("/concessions/events", methods=["POST"])
@require_auth([M])
def create_event():
    body = util.get_json_body()
    venue_id = util.require_field(body, "venue_id")
    name = util.as_nonempty_string(util.require_field(body, "name"), "name")
    doors_time = util.parse_datetime(util.require_field(body, "doors_time"), "doors_time")
    end_time = util.parse_datetime(util.require_field(body, "end_time"), "end_time")
    event_multiplier_pct = body.get("event_multiplier_pct", 100)
    util.as_int(event_multiplier_pct, "event_multiplier_pct")
    if event_multiplier_pct < 50 or event_multiplier_pct > 300:
        raise errors.invalid_request("event_multiplier_pct must be between 50 and 300.")
    if not (end_time > doors_time):
        raise errors.invalid_request("end_time must be strictly after doors_time.")

    with store.lock:
        util.lookup(store.venues, venue_id)
        # Window-overlap check vs other non-SETTLED events at the same venue.
        # Closed interval: a shared boundary instant IS an overlap (PRD §3.2).
        for ev in store.events.values():
            if ev["venue_id"] != venue_id:
                continue
            if ev["status"] == "SETTLED":
                continue
            # Closed-interval overlap: doors_time <= other.end_time AND
            # other.doors_time <= end_time.
            if doors_time <= ev["end_time"] and ev["doors_time"] <= end_time:
                raise errors.event_window_overlap()
        e = {
            "venue_id": venue_id,
            "name": name,
            "doors_time": doors_time,
            "end_time": end_time,
            "event_multiplier_pct": event_multiplier_pct,
            "peak_window": False,
            "status": "SCHEDULED",
            "gross_sales_cents": 0,
            "waste_cost_cents": 0,
        }
        util.stamp_create(e)
        store.events[e["id"]] = e
    return object_response(S.event(e), 201)


@app.route("/concessions/events/<eid>", methods=["GET"])
@require_auth([M, R, O, P])
def get_event(eid):
    e = util.lookup(store.events, eid)
    return object_response(S.event(e))


@app.route("/concessions/venues/<vid>/events", methods=["GET"])
@require_auth([M, R, O, P])
def list_venue_events(vid):
    util.lookup(store.venues, vid)
    return list_response(store.events.values(), S.event, lambda o: o["venue_id"] == vid)


@app.route("/concessions/events/<eid>/open-doors", methods=["POST"])
@require_auth([M])
def open_doors(eid):
    with store.lock:
        e = util.lookup(store.events, eid)
        if e["status"] != "SCHEDULED":
            raise errors.invalid_state()
        # Precondition: at least one Stand exists for the event (PRD §3.3).
        has_stand = any(s["event_id"] == eid for s in store.stands.values())
        if not has_stand:
            raise errors.invalid_state("Event has no stands.")
        e["status"] = "DOORS_OPEN"
        util.touch(e)
    return object_response(S.event(e))


@app.route("/concessions/events/<eid>/peak-window/open", methods=["POST"])
@require_auth([M])
def peak_window_open(eid):
    with store.lock:
        e = util.lookup(store.events, eid)
        # DOORS_OPEN -> IN_PROGRESS (peak true), or IN_PROGRESS self-loop when
        # peak_window is currently false. Otherwise invalid state.
        if e["status"] == "DOORS_OPEN":
            pass
        elif e["status"] == "IN_PROGRESS" and e["peak_window"] is False:
            pass
        else:
            raise errors.invalid_state()
        e["status"] = "IN_PROGRESS"
        e["peak_window"] = True
        util.touch(e)
        # Two-part cascade (PRD §3.3): recompute menu prices and open-stand staffing.
        services.recompute_menu_prices_for_event(e)
        services.recompute_open_stands_staffing(e)
    return object_response(S.event(e))


@app.route("/concessions/events/<eid>/peak-window/close", methods=["POST"])
@require_auth([M])
def peak_window_close(eid):
    with store.lock:
        e = util.lookup(store.events, eid)
        # Self-loop available only while IN_PROGRESS and peak_window currently true.
        if not (e["status"] == "IN_PROGRESS" and e["peak_window"] is True):
            raise errors.invalid_state()
        e["peak_window"] = False
        util.touch(e)
        services.recompute_menu_prices_for_event(e)
        services.recompute_open_stands_staffing(e)
    return object_response(S.event(e))


@app.route("/concessions/events/<eid>/settle", methods=["POST"])
@require_auth([M])
def settle_event(eid):
    with store.lock:
        e = util.lookup(store.events, eid)
        if e["status"] != "IN_PROGRESS":
            raise errors.invalid_state()
        # Settlement gate (PRD §3.3): every child Stand CLOSED, no child Order
        # PLACED or READY.
        for s in store.stands.values():
            if s["event_id"] == eid and s["status"] != "CLOSED":
                raise errors.event_not_settleable()
        for ordr in store.orders.values():
            if ordr["event_id"] == eid and ordr["fulfillment_status"] in ("PLACED", "READY"):
                raise errors.event_not_settleable()

        if e["peak_window"] is True:
            e["peak_window"] = False
        e["status"] = "SETTLED"
        util.touch(e)

        venue = store.venues[
            # Event.venue_id always references an existing venue.
            e["venue_id"]
        ]
        gross = e["gross_sales_cents"]
        waste = e["waste_cost_cents"]
        venue_share, operator_net = services.compute_revenue_share(gross, waste, venue)
        stmt = {
            "event_id": eid,
            "gross_sales_cents": gross,
            "waste_cost_cents": waste,
            "venue_share_cents": venue_share,
            "operator_net_cents": operator_net,
        }
        util.stamp_create(stmt)
        store.revenue_share_statements[stmt["id"]] = stmt
    return object_response(S.revenue_share_statement(stmt), 201)


@app.route("/concessions/events/<eid>/revenue-share-statement", methods=["GET"])
@require_auth([M])
def get_revenue_share_statement(eid):
    util.lookup(store.events, eid)
    return list_response(
        store.revenue_share_statements.values(),
        S.revenue_share_statement,
        lambda o: o["event_id"] == eid,
    )


# ===========================================================================
# Stand
# ===========================================================================
@app.route("/concessions/stands", methods=["POST"])
@require_auth([M])
def create_stand():
    body = util.get_json_body()
    event_id = util.require_field(body, "event_id")
    name = util.as_nonempty_string(util.require_field(body, "name"), "name")
    demand_tier = body.get("demand_tier", "MID")
    util.as_enum(demand_tier, "demand_tier", {"LOW", "MID", "HIGH"})
    expected_orders_per_hour = body.get("expected_orders_per_hour", 0)
    util.as_int(expected_orders_per_hour, "expected_orders_per_hour")
    if expected_orders_per_hour < 0:
        raise errors.invalid_request("expected_orders_per_hour must be >= 0.")

    with store.lock:
        util.lookup(store.events, event_id)
        s = {
            "event_id": event_id,
            "name": name,
            "demand_tier": demand_tier,
            "expected_orders_per_hour": expected_orders_per_hour,
            "status": "CLOSED",
            "required_staff": 0,
            "assigned_staff_count": 0,
        }
        util.stamp_create(s)
        store.stands[s["id"]] = s
    return object_response(S.stand(s), 201)


@app.route("/concessions/stands/<sid>", methods=["GET"])
@require_auth([M, R, O, P])
def get_stand(sid):
    s = util.lookup(store.stands, sid)
    return object_response(S.stand(s))


@app.route("/concessions/events/<eid>/stands", methods=["GET"])
@require_auth([M, R, O, P])
def list_event_stands(eid):
    util.lookup(store.events, eid)
    return list_response(store.stands.values(), S.stand, lambda o: o["event_id"] == eid)


@app.route("/concessions/stands/<sid>/open", methods=["POST"])
@require_auth([O])
def open_stand(sid):
    with store.lock:
        s = util.lookup(store.stands, sid)
        # State check first (priority 5): open is defined from CLOSED or SUSPENDED.
        if s["status"] not in ("CLOSED", "SUSPENDED"):
            raise errors.invalid_state()
        e = store.events[s["event_id"]]
        # Business safety priority 7: parent event DOORS_OPEN or IN_PROGRESS.
        if e["status"] not in ("DOORS_OPEN", "IN_PROGRESS"):
            raise errors.event_not_openable()
        # Business safety priority 8: assigned_staff_count >= 1.
        if s["assigned_staff_count"] < 1:
            raise errors.understaffed_open()
        s["status"] = "OPEN"
        s["required_staff"] = services.compute_required_staff(s, e)
        util.touch(s)
    return object_response(S.stand(s))


@app.route("/concessions/stands/<sid>/suspend", methods=["POST"])
@require_auth([O])
def suspend_stand(sid):
    with store.lock:
        s = util.lookup(store.stands, sid)
        if s["status"] != "OPEN":
            raise errors.invalid_state()
        s["status"] = "SUSPENDED"
        util.touch(s)
    return object_response(S.stand(s))


@app.route("/concessions/stands/<sid>/close", methods=["POST"])
@require_auth([O])
def close_stand(sid):
    with store.lock:
        s = util.lookup(store.stands, sid)
        if s["status"] not in ("OPEN", "SUSPENDED"):
            raise errors.invalid_state()
        # Precondition: no order at this stand in PLACED or READY (PRD §3.3).
        for ordr in store.orders.values():
            if ordr["stand_id"] == sid and ordr["fulfillment_status"] in ("PLACED", "READY"):
                raise errors.invalid_state("Stand has unfulfilled orders.")
        s["status"] = "CLOSED"
        util.touch(s)
    return object_response(S.stand(s))


@app.route("/concessions/stands/<sid>/expire-lots", methods=["POST"])
@require_auth([R])
def expire_lots(sid):
    with store.lock:
        s = util.lookup(store.stands, sid)
        e = store.events[s["event_id"]]
        venue = store.venues[e["venue_id"]]
        now = store.current_utc()
        # Each ACTIVE lot with expires_at non-null and <= now and remaining_qty > 0.
        target_lots = [
            lot for lot in store.inventory_lots.values()
            if lot["stand_id"] == sid
            and lot["status"] == "ACTIVE"
            and lot["expires_at"] is not None
            and lot["expires_at"] <= now
            and lot["remaining_qty"] > 0
        ]
        target_lots.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
        for lot in target_lots:
            qty = lot["remaining_qty"]
            # Cost the EXPIRY waste per spoilage policy, drawn from the named lot.
            cost = services.compute_waste_cost(venue, sid, lot["product_id"], qty)
            wr = {
                "stand_id": sid,
                "product_id": lot["product_id"],
                "lot_id": lot["id"],
                "reason": "EXPIRY",
                "qty": qty,
                "cost_cents": cost,
            }
            util.stamp_create(wr, with_version=False)
            store.waste_records[wr["id"]] = wr
            # Bump parent event waste_cost_cents (cross-aggregate ledger sync).
            e["waste_cost_cents"] += cost
            util.touch(e)
            # Set lot remaining_qty = 0 and status = EXPIRED.
            lot["remaining_qty"] = 0
            lot["status"] = "EXPIRED"
            util.touch(lot)
    return object_response(S.stand(s))


@app.route("/concessions/stands/<sid>/replenishment-suggestions", methods=["GET"])
@require_auth([M, R])
def replenishment_suggestions(sid):
    util.lookup(store.stands, sid)
    # Group ACTIVE lots by product (PRD §3.7). Deterministic order by first
    # appearance (created_at) of each product.
    by_product = {}
    order_seen = []
    active = [
        lot for lot in store.inventory_lots.values()
        if lot["stand_id"] == sid and lot["status"] == "ACTIVE"
    ]
    active.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
    for lot in active:
        pid = lot["product_id"]
        if pid not in by_product:
            by_product[pid] = []
            order_seen.append(pid)
        by_product[pid].append(lot)

    suggestions = []
    for pid in order_seen:
        lots = by_product[pid]
        oh = sum(lot["remaining_qty"] for lot in lots)
        par = max(lot["par_level"] for lot in lots)
        reorder = max(lot["reorder_point"] for lot in lots)
        if oh <= reorder:  # inclusive (PRD §3.7)
            suggestions.append({
                "product_id": pid,
                "on_hand": oh,
                "suggested_qty": par - oh,
            })
    # Advisory list — not a paginated entity collection, but follow array envelope.
    limit, offset = util.parse_pagination()
    page, total = util.paginate(suggestions, limit, offset)
    return array_response(page, limit, offset, total)


# ===========================================================================
# MenuItem
# ===========================================================================
@app.route("/concessions/menu-items", methods=["POST"])
@require_auth([M])
def create_menu_item():
    body = util.get_json_body()
    stand_id = util.require_field(body, "stand_id")
    product_id = util.require_field(body, "product_id")
    available = body.get("available", True)
    util.as_bool(available, "available")

    with store.lock:
        stand = util.lookup(store.stands, stand_id)
        product = util.lookup(store.products, product_id)
        event = store.events[stand["event_id"]]
        price = services.compute_item_price(product, event, stand)
        mi = {
            "stand_id": stand_id,
            "product_id": product_id,
            "available": available,
            "price_cents": price,
        }
        util.stamp_create(mi)
        store.menu_items[mi["id"]] = mi
    return object_response(S.menu_item(mi), 201)


@app.route("/concessions/menu-items/<mid>", methods=["GET"])
@require_auth([M, R, O, P])
def get_menu_item(mid):
    mi = util.lookup(store.menu_items, mid)
    return object_response(S.menu_item(mi))


@app.route("/concessions/stands/<sid>/menu-items", methods=["GET"])
@require_auth([M, R, O, P])
def list_stand_menu_items(sid):
    util.lookup(store.stands, sid)
    return list_response(store.menu_items.values(), S.menu_item, lambda o: o["stand_id"] == sid)


@app.route("/concessions/menu-items", methods=["GET"])
@require_auth([M, R, O, P])
def list_menu_items():
    product_id = request.args.get("product_id")
    pred = (lambda o: o["product_id"] == product_id) if product_id is not None else None
    return list_response(store.menu_items.values(), S.menu_item, pred)


# ===========================================================================
# InventoryLot
# ===========================================================================
@app.route("/concessions/inventory-lots", methods=["POST"])
@require_auth([M, R])
def create_inventory_lot():
    body = util.get_json_body()
    stand_id = util.require_field(body, "stand_id")
    product_id = util.require_field(body, "product_id")
    received_qty = util.as_int(util.require_field(body, "received_qty"), "received_qty")
    par_level = util.as_int(util.require_field(body, "par_level"), "par_level")
    reorder_point = util.as_int(util.require_field(body, "reorder_point"), "reorder_point")
    if received_qty <= 0:
        raise errors.invalid_request("received_qty must be > 0.")
    if par_level < 0:
        raise errors.invalid_request("par_level must be >= 0.")
    if reorder_point < 0 or reorder_point > par_level:
        raise errors.invalid_request("reorder_point must be between 0 and par_level.")
    expires_at_raw = body.get("expires_at")
    expires_at = None
    if expires_at_raw is not None:
        expires_at = util.parse_datetime(expires_at_raw, "expires_at")

    with store.lock:
        util.lookup(store.stands, stand_id)
        product = util.lookup(store.products, product_id)
        unit_cost = body.get("unit_cost_cents")
        if unit_cost is None:
            unit_cost = product["unit_cost_cents"]
        else:
            util.as_int(unit_cost, "unit_cost_cents")
            if unit_cost < 0:
                raise errors.invalid_request("unit_cost_cents must be >= 0.")
        lot = {
            "stand_id": stand_id,
            "product_id": product_id,
            "received_qty": received_qty,
            "remaining_qty": received_qty,
            "unit_cost_cents": unit_cost,
            "par_level": par_level,
            "reorder_point": reorder_point,
            "expires_at": expires_at,
            "status": "ACTIVE",
        }
        util.stamp_create(lot)
        store.inventory_lots[lot["id"]] = lot
    return object_response(S.inventory_lot(lot), 201)


@app.route("/concessions/inventory-lots/<lid>", methods=["GET"])
@require_auth([M, R, O])
def get_inventory_lot(lid):
    lot = util.lookup(store.inventory_lots, lid)
    return object_response(S.inventory_lot(lot))


@app.route("/concessions/stands/<sid>/inventory-lots", methods=["GET"])
@require_auth([M, R, O])
def list_stand_inventory_lots(sid):
    util.lookup(store.stands, sid)
    product_id = request.args.get("product_id")

    def pred(o):
        if o["stand_id"] != sid:
            return False
        if product_id is not None and o["product_id"] != product_id:
            return False
        return True

    return list_response(store.inventory_lots.values(), S.inventory_lot, pred)


@app.route("/concessions/inventory-lots", methods=["GET"])
@require_auth([M, R, O])
def list_inventory_lots():
    product_id = request.args.get("product_id")
    pred = (lambda o: o["product_id"] == product_id) if product_id is not None else None
    return list_response(store.inventory_lots.values(), S.inventory_lot, pred)


# ===========================================================================
# Replenishment
# ===========================================================================
@app.route("/concessions/replenishments", methods=["POST"])
@require_auth([M, R, O])
def create_replenishment():
    body = util.get_json_body()
    stand_id = util.require_field(body, "stand_id")
    product_id = util.require_field(body, "product_id")
    requested_qty = util.as_int(util.require_field(body, "requested_qty"), "requested_qty")
    if requested_qty <= 0:
        raise errors.invalid_request("requested_qty must be > 0.")

    with store.lock:
        util.lookup(store.stands, stand_id)
        util.lookup(store.products, product_id)
        rep = {
            "stand_id": stand_id,
            "product_id": product_id,
            "requested_qty": requested_qty,
            "fulfilled_qty": 0,
            "status": "REQUESTED",
        }
        util.stamp_create(rep)
        store.replenishments[rep["id"]] = rep
    return object_response(S.replenishment(rep), 201)


@app.route("/concessions/replenishments/<rid>", methods=["GET"])
@require_auth([M, R, O])
def get_replenishment(rid):
    rep = util.lookup(store.replenishments, rid)
    return object_response(S.replenishment(rep))


@app.route("/concessions/replenishments", methods=["GET"])
@require_auth([M, R, O])
def list_replenishments():
    stand_id = request.args.get("stand_id")
    product_id = request.args.get("product_id")

    def pred(o):
        if stand_id is not None and o["stand_id"] != stand_id:
            return False
        if product_id is not None and o["product_id"] != product_id:
            return False
        return True

    return list_response(store.replenishments.values(), S.replenishment, pred)


@app.route("/concessions/replenishments/<rid>/pick", methods=["POST"])
@require_auth([R])
def pick_replenishment(rid):
    with store.lock:
        rep = util.lookup(store.replenishments, rid)
        if rep["status"] != "REQUESTED":
            raise errors.invalid_state()
        rep["status"] = "PICKING"
        util.touch(rep)
    return object_response(S.replenishment(rep))


@app.route("/concessions/replenishments/<rid>/deliver", methods=["POST"])
@require_auth([R])
def deliver_replenishment(rid):
    body = util.get_json_body()
    par_level = util.as_int(util.require_field(body, "par_level"), "par_level")
    reorder_point = util.as_int(util.require_field(body, "reorder_point"), "reorder_point")
    if par_level < 0:
        raise errors.invalid_request("par_level must be >= 0.")
    if reorder_point < 0 or reorder_point > par_level:
        raise errors.invalid_request("reorder_point must be between 0 and par_level.")

    with store.lock:
        rep = util.lookup(store.replenishments, rid)
        if rep["status"] != "PICKING":
            raise errors.invalid_state()
        stand = store.stands[rep["stand_id"]]
        event = store.events[stand["event_id"]]
        # Destination stand OPEN/SUSPENDED/CLOSED and event non-SETTLED (PRD §3.5).
        if event["status"] == "SETTLED":
            raise errors.invalid_state("Destination event is SETTLED.")
        product = store.products[rep["product_id"]]
        rep["fulfilled_qty"] = rep["requested_qty"]
        rep["status"] = "DELIVERED"
        util.touch(rep)
        lot = {
            "stand_id": rep["stand_id"],
            "product_id": rep["product_id"],
            "received_qty": rep["fulfilled_qty"],
            "remaining_qty": rep["fulfilled_qty"],
            "unit_cost_cents": product["unit_cost_cents"],
            "par_level": par_level,
            "reorder_point": reorder_point,
            "expires_at": None,
            "status": "ACTIVE",
        }
        util.stamp_create(lot)
        store.inventory_lots[lot["id"]] = lot
    return object_response(S.replenishment(rep))


@app.route("/concessions/replenishments/<rid>/cancel", methods=["POST"])
@require_auth([R])
def cancel_replenishment(rid):
    with store.lock:
        rep = util.lookup(store.replenishments, rid)
        if rep["status"] not in ("REQUESTED", "PICKING"):
            raise errors.invalid_state()
        rep["status"] = "CANCELLED"
        util.touch(rep)
    return object_response(S.replenishment(rep))


# ===========================================================================
# Transfer
# ===========================================================================
def _same_event_distinct(from_stand, to_stand):
    if from_stand["id"] == to_stand["id"]:
        return False
    if from_stand["event_id"] != to_stand["event_id"]:
        return False
    return True


@app.route("/concessions/transfers", methods=["POST"])
@require_auth([M, R])
def create_transfer():
    body = util.get_json_body()
    from_stand_id = util.require_field(body, "from_stand_id")
    to_stand_id = util.require_field(body, "to_stand_id")
    product_id = util.require_field(body, "product_id")
    qty = util.as_int(util.require_field(body, "qty"), "qty")
    if qty <= 0:
        raise errors.invalid_request("qty must be > 0.")

    with store.lock:
        from_stand = util.lookup(store.stands, from_stand_id)
        to_stand = util.lookup(store.stands, to_stand_id)
        util.lookup(store.products, product_id)
        # Same-event distinct-stands check at draft (PRD §3.5).
        if not _same_event_distinct(from_stand, to_stand):
            raise errors.cross_event_transfer()
        t = {
            "from_stand_id": from_stand_id,
            "to_stand_id": to_stand_id,
            "product_id": product_id,
            "qty": qty,
            "status": "DRAFT",
            "_debited": None,  # list of (lot_id, units) recorded at dispatch
        }
        util.stamp_create(t)
        store.transfers[t["id"]] = t
    return object_response(S.transfer(t), 201)


@app.route("/concessions/transfers/<tid>", methods=["GET"])
@require_auth([M, R])
def get_transfer(tid):
    t = util.lookup(store.transfers, tid)
    return object_response(S.transfer(t))


@app.route("/concessions/transfers", methods=["GET"])
@require_auth([M, R])
def list_transfers():
    from_stand_id = request.args.get("from_stand_id")
    to_stand_id = request.args.get("to_stand_id")
    product_id = request.args.get("product_id")

    def pred(o):
        if from_stand_id is not None and o["from_stand_id"] != from_stand_id:
            return False
        if to_stand_id is not None and o["to_stand_id"] != to_stand_id:
            return False
        if product_id is not None and o["product_id"] != product_id:
            return False
        return True

    return list_response(store.transfers.values(), S.transfer, pred)


@app.route("/concessions/transfers/<tid>/dispatch", methods=["POST"])
@require_auth([R])
def dispatch_transfer(tid):
    body = util.get_json_body()
    expected_version = util.require_field(body, "expected_from_stand_version")
    util.as_int(expected_version, "expected_from_stand_version")

    with store.lock:
        t = util.lookup(store.transfers, tid)
        # State check (priority 5) before OCC (priority 6).
        if t["status"] != "DRAFT":
            raise errors.invalid_state()
        from_stand = store.stands[t["from_stand_id"]]
        to_stand = store.stands[t["to_stand_id"]]
        # OCC on source stand version (priority 6).
        if expected_version != from_stand["version"]:
            raise errors.stale_stand_version()
        # Same-event distinct re-check at dispatch (priority 12).
        if not _same_event_distinct(from_stand, to_stand):
            raise errors.cross_event_transfer()
        # Source on-hand >= qty (priority 16).
        if services.on_hand(t["from_stand_id"], t["product_id"]) < t["qty"]:
            raise errors.transfer_qty_exceeds_onhand()
        # Debit FIFO; record what was taken for weighted-avg costing.
        taken = services.debit_fifo(t["from_stand_id"], t["product_id"], t["qty"])
        t["_debited"] = [(lot["id"], units) for lot, units in taken]
        t["_wavg_cost"] = services.weighted_avg_cost_of_taken(taken)
        t["status"] = "IN_TRANSIT"
        util.touch(t)
        # Bump source Stand.version (PRD §2.7).
        util.touch(from_stand)
    return object_response(S.transfer(t))


@app.route("/concessions/transfers/<tid>/complete", methods=["POST"])
@require_auth([R])
def complete_transfer(tid):
    with store.lock:
        t = util.lookup(store.transfers, tid)
        if t["status"] != "IN_TRANSIT":
            raise errors.invalid_state()
        to_stand = store.stands[t["to_stand_id"]]
        to_event = store.events[to_stand["event_id"]]
        if to_event["status"] == "SETTLED":
            raise errors.invalid_state("Destination event is SETTLED.")
        lot = {
            "stand_id": t["to_stand_id"],
            "product_id": t["product_id"],
            "received_qty": t["qty"],
            "remaining_qty": t["qty"],
            "unit_cost_cents": t.get("_wavg_cost", 0),
            "par_level": 0,
            "reorder_point": 0,
            "expires_at": None,
            "status": "ACTIVE",
        }
        util.stamp_create(lot)
        store.inventory_lots[lot["id"]] = lot
        t["status"] = "COMPLETED"
        util.touch(t)
    return object_response(S.transfer(t))


@app.route("/concessions/transfers/<tid>/cancel", methods=["POST"])
@require_auth([R])
def cancel_transfer(tid):
    with store.lock:
        t = util.lookup(store.transfers, tid)
        if t["status"] not in ("DRAFT", "IN_TRANSIT"):
            raise errors.invalid_state()
        if t["status"] == "IN_TRANSIT":
            # Compensation: re-credit qty to from_stand as a new ACTIVE lot
            # at the same weighted-average cost (PRD §3.5).
            lot = {
                "stand_id": t["from_stand_id"],
                "product_id": t["product_id"],
                "received_qty": t["qty"],
                "remaining_qty": t["qty"],
                "unit_cost_cents": t.get("_wavg_cost", 0),
                "par_level": 0,
                "reorder_point": 0,
                "expires_at": None,
                "status": "ACTIVE",
            }
            util.stamp_create(lot)
            store.inventory_lots[lot["id"]] = lot
        t["status"] = "CANCELLED"
        util.touch(t)
    return object_response(S.transfer(t))


# ===========================================================================
# WasteRecord
# ===========================================================================
@app.route("/concessions/waste-records", methods=["POST"])
@require_auth([R])
def create_waste_record():
    body = util.get_json_body()
    stand_id = util.require_field(body, "stand_id")
    product_id = util.require_field(body, "product_id")
    reason = util.require_field(body, "reason")
    util.as_enum(reason, "reason", {"EXPIRY", "SPILLAGE", "DAMAGE"})
    qty = util.as_int(util.require_field(body, "qty"), "qty")
    if qty <= 0:
        raise errors.invalid_request("qty must be > 0.")
    lot_id = body.get("lot_id")

    with store.lock:
        stand = util.lookup(store.stands, stand_id)
        util.lookup(store.products, product_id)
        event = store.events[stand["event_id"]]
        venue = store.venues[event["venue_id"]]
        named_lot = None
        if lot_id is not None:
            named_lot = util.lookup(store.inventory_lots, lot_id)

        cost = services.compute_waste_cost(venue, stand_id, product_id, qty)
        wr = {
            "stand_id": stand_id,
            "product_id": product_id,
            "lot_id": lot_id,
            "reason": reason,
            "qty": qty,
            "cost_cents": cost,
        }
        util.stamp_create(wr, with_version=False)
        store.waste_records[wr["id"]] = wr
        # Bump parent event waste_cost_cents.
        event["waste_cost_cents"] += cost
        util.touch(event)
        # Decrement on-hand: FIFO across lots for SPILLAGE/DAMAGE; named lot for EXPIRY.
        if reason == "EXPIRY" and named_lot is not None:
            take = min(named_lot["remaining_qty"], qty)
            named_lot["remaining_qty"] -= take
            if named_lot["remaining_qty"] == 0 and named_lot["status"] == "ACTIVE":
                named_lot["status"] = "DEPLETED"
            util.touch(named_lot)
        else:
            services.debit_fifo(stand_id, product_id, min(qty, services.on_hand(stand_id, product_id)))
    return object_response(S.waste_record(wr), 201)


@app.route("/concessions/waste-records/<wid>", methods=["GET"])
@require_auth([M, R])
def get_waste_record(wid):
    wr = util.lookup(store.waste_records, wid)
    return object_response(S.waste_record(wr))


@app.route("/concessions/waste-records", methods=["GET"])
@require_auth([M, R])
def list_waste_records():
    stand_id = request.args.get("stand_id")
    product_id = request.args.get("product_id")
    lot_id = request.args.get("lot_id")

    def pred(o):
        if stand_id is not None and o["stand_id"] != stand_id:
            return False
        if product_id is not None and o["product_id"] != product_id:
            return False
        if lot_id is not None and o["lot_id"] != lot_id:
            return False
        return True

    return list_response(store.waste_records.values(), S.waste_record, pred)


# ===========================================================================
# Patron
# ===========================================================================
@app.route("/concessions/patrons", methods=["POST"])
@require_auth([P, M])
def create_patron():
    body = util.get_json_body()
    display_name = util.as_nonempty_string(util.require_field(body, "display_name"), "display_name")
    with store.lock:
        pt = {
            "display_name": display_name,
            "wallet_credit_cents": 0,
        }
        util.stamp_create(pt)
        store.patrons[pt["id"]] = pt
    return object_response(S.patron(pt), 201)


@app.route("/concessions/patrons/<pid>", methods=["GET"])
@require_auth([M, P])
def get_patron(pid):
    pt = util.lookup(store.patrons, pid)
    return object_response(S.patron(pt))


# ===========================================================================
# Order / OrderLine
# ===========================================================================
def _check_order_owner(order):
    """If the caller is a Patron, they must own the order (PRD §2.1)."""
    if g.user_role == "Patron" and order["patron_id"] != g.user_id:
        raise errors.not_order_owner()


@app.route("/concessions/orders", methods=["POST"])
@require_auth([P])
def create_order():
    body = util.get_json_body()
    event_id = util.require_field(body, "event_id")
    stand_id = util.require_field(body, "stand_id")
    patron_id = util.require_field(body, "patron_id")

    with store.lock:
        util.lookup(store.events, event_id)
        util.lookup(store.stands, stand_id)
        util.lookup(store.patrons, patron_id)
        # Ownership: the Patron creates orders for themselves (PRD §2.1).
        if g.user_role == "Patron" and patron_id != g.user_id:
            raise errors.not_order_owner()
        ordr = {
            "event_id": event_id,
            "stand_id": stand_id,
            "patron_id": patron_id,
            "subtotal_cents": 0,
            "service_fee_cents": 0,
            "total_cents": 0,
            "payment_status": "UNPAID",
            "fulfillment_status": "CART",
        }
        util.stamp_create(ordr)
        store.orders[ordr["id"]] = ordr
    return object_response(S.order(ordr), 201)


@app.route("/concessions/orders/<oid>", methods=["GET"])
@require_auth([M, O, P])
def get_order(oid):
    ordr = util.lookup(store.orders, oid)
    _check_order_owner(ordr)
    return object_response(S.order(ordr))


@app.route("/concessions/orders", methods=["GET"])
@require_auth([M, O, P])
def list_orders():
    event_id = request.args.get("event_id")
    stand_id = request.args.get("stand_id")
    patron_id = request.args.get("patron_id")

    def pred(o):
        if event_id is not None and o["event_id"] != event_id:
            return False
        if stand_id is not None and o["stand_id"] != stand_id:
            return False
        if patron_id is not None and o["patron_id"] != patron_id:
            return False
        # A Patron only sees their own orders.
        if g.user_role == "Patron" and o["patron_id"] != g.user_id:
            return False
        return True

    return list_response(store.orders.values(), S.order, pred)


@app.route("/concessions/orders/<oid>/lines", methods=["POST"])
@require_auth([P])
def add_order_line(oid):
    body = util.get_json_body()
    menu_item_id = util.require_field(body, "menu_item_id")
    qty = util.as_int(util.require_field(body, "qty"), "qty")
    if qty <= 0:
        raise errors.invalid_request("qty must be > 0.")

    with store.lock:
        ordr = util.lookup(store.orders, oid)
        _check_order_owner(ordr)
        # Lines may only be added while CART (state check).
        if ordr["fulfillment_status"] != "CART":
            raise errors.invalid_state()
        mi = util.lookup(store.menu_items, menu_item_id)
        # Snapshot unit_price_cents from the menu item's current price (PRD §3.8).
        unit_price = mi["price_cents"]
        line = {
            "order_id": oid,
            "menu_item_id": menu_item_id,
            "qty": qty,
            "unit_price_cents": unit_price,
            "line_subtotal_cents": unit_price * qty,
            "line_fee_cents": 0,
        }
        # line_fee uses the venue's service_fee_pct (PRD §3.8).
        event = store.events[ordr["event_id"]]
        venue = store.venues[event["venue_id"]]
        services.compute_line_fields(line, venue["service_fee_pct"])
        util.stamp_create(line)
        store.order_lines[line["id"]] = line
        # Adding a line recomputes the order totals from current lines.
        services.recompute_order_totals(ordr, venue)
        util.touch(ordr)
    return object_response(S.order_line(line), 201)


@app.route("/concessions/orders/<oid>/lines", methods=["GET"])
@require_auth([M, O, P])
def list_order_lines(oid):
    ordr = util.lookup(store.orders, oid)
    _check_order_owner(ordr)
    return list_response(store.order_lines.values(), S.order_line, lambda o: o["order_id"] == oid)


@app.route("/concessions/order-lines/<lid>", methods=["GET"])
@require_auth([M, O, P])
def get_order_line(lid):
    line = util.lookup(store.order_lines, lid)
    ordr = store.orders[line["order_id"]]
    _check_order_owner(ordr)
    return object_response(S.order_line(line))


@app.route("/concessions/order-lines", methods=["GET"])
@require_auth([M, O, P])
def list_order_lines_global():
    menu_item_id = request.args.get("menu_item_id")

    def pred(o):
        if menu_item_id is not None and o["menu_item_id"] != menu_item_id:
            return False
        if g.user_role == "Patron":
            ordr = store.orders.get(o["order_id"])
            if ordr is None or ordr["patron_id"] != g.user_id:
                return False
        return True

    return list_response(store.order_lines.values(), S.order_line, pred)


@app.route("/concessions/orders/<oid>/place", methods=["POST"])
@require_auth([P])
def place_order(oid):
    with store.lock:
        ordr = util.lookup(store.orders, oid)
        _check_order_owner(ordr)
        # State check (priority 5).
        if ordr["fulfillment_status"] != "CART":
            raise errors.invalid_state()
        stand = store.stands[ordr["stand_id"]]
        lines = services.lines_of_order(oid)
        # Order must have >= 1 line. (PRD §3.8 placement requirement.)
        if len(lines) < 1:
            raise errors.invalid_state("Order has no lines.")
        # Stand must be OPEN (priority 9).
        if stand["status"] != "OPEN":
            raise errors.stand_not_open()
        # Stock sufficiency per line (priority 15): aggregate required qty per product.
        required = {}
        for line in lines:
            mi = store.menu_items[line["menu_item_id"]]
            required[mi["product_id"]] = required.get(mi["product_id"], 0) + line["qty"]
        for product_id, need in required.items():
            if services.on_hand(stand["id"], product_id) < need:
                raise errors.insufficient_stock()
        # Recompute totals; advance fulfillment.
        event = store.events[ordr["event_id"]]
        venue = store.venues[event["venue_id"]]
        services.recompute_order_totals(ordr, venue)
        ordr["fulfillment_status"] = "PLACED"
        util.touch(ordr)
    return object_response(S.order(ordr))


@app.route("/concessions/orders/<oid>/pay", methods=["POST"])
@require_auth([P])
def pay_order(oid):
    with store.lock:
        ordr = util.lookup(store.orders, oid)
        _check_order_owner(ordr)
        # Payment transition defined from PLACED fulfillment + UNPAID payment.
        if not (ordr["fulfillment_status"] == "PLACED" and ordr["payment_status"] == "UNPAID"):
            raise errors.invalid_state()
        ordr["payment_status"] = "PAID"
        util.touch(ordr)
    return object_response(S.order(ordr))


@app.route("/concessions/orders/<oid>/ready", methods=["POST"])
@require_auth([O])
def ready_order(oid):
    body = util.get_json_body()
    expected_version = util.require_field(body, "expected_stand_version")
    util.as_int(expected_version, "expected_stand_version")

    with store.lock:
        ordr = util.lookup(store.orders, oid)
        # State check (priority 5): ready defined from fulfillment PLACED.
        if ordr["fulfillment_status"] != "PLACED":
            raise errors.invalid_state()
        stand = store.stands[ordr["stand_id"]]
        # OCC on stand version (priority 6).
        if expected_version != stand["version"]:
            raise errors.stale_stand_version()
        # Payment gate (priority 10).
        if ordr["payment_status"] != "PAID":
            raise errors.order_unpaid()
        # Stock sufficiency (priority 15).
        lines = services.lines_of_order(oid)
        required = {}
        for line in lines:
            mi = store.menu_items[line["menu_item_id"]]
            required[mi["product_id"]] = required.get(mi["product_id"], 0) + line["qty"]
        for product_id, need in required.items():
            if services.on_hand(stand["id"], product_id) < need:
                raise errors.insufficient_stock()
        # Consume stock FIFO per product.
        for product_id, need in required.items():
            services.debit_fifo(stand["id"], product_id, need)
        ordr["fulfillment_status"] = "READY"
        util.touch(ordr)
        # Bump Stand.version (PRD §2.7).
        util.touch(stand)
    return object_response(S.order(ordr))


@app.route("/concessions/orders/<oid>/pickup", methods=["POST"])
@require_auth([O])
def pickup_order(oid):
    with store.lock:
        ordr = util.lookup(store.orders, oid)
        if ordr["fulfillment_status"] != "READY":
            raise errors.invalid_state()
        ordr["fulfillment_status"] = "PICKED_UP"
        util.touch(ordr)
        # Sale reaches the event ledger (PRD §3.8).
        event = store.events[ordr["event_id"]]
        event["gross_sales_cents"] += ordr["total_cents"]
        util.touch(event)
    return object_response(S.order(ordr))


@app.route("/concessions/orders/<oid>/cancel", methods=["POST"])
@require_auth([P])
def cancel_order(oid):
    with store.lock:
        ordr = util.lookup(store.orders, oid)
        _check_order_owner(ordr)
        # Cancel defined only from fulfillment PLACED (PRD §3.8).
        if ordr["fulfillment_status"] != "PLACED":
            raise errors.invalid_state()
        if ordr["payment_status"] == "PAID":
            # Compensating refund to wallet (PRD §3.8).
            ordr["payment_status"] = "REFUNDED"
            patron = store.patrons[ordr["patron_id"]]
            patron["wallet_credit_cents"] += ordr["total_cents"]
            util.touch(patron)
        ordr["fulfillment_status"] = "CANCELLED"
        util.touch(ordr)
    return object_response(S.order(ordr))


# ===========================================================================
# StaffShift
# ===========================================================================
@app.route("/concessions/staff-shifts", methods=["POST"])
@require_auth([M])
def create_staff_shift():
    body = util.get_json_body()
    stand_id = util.require_field(body, "stand_id")
    worker_name = util.as_nonempty_string(util.require_field(body, "worker_name"), "worker_name")
    shift_start = util.parse_datetime(util.require_field(body, "shift_start"), "shift_start")
    shift_end = util.parse_datetime(util.require_field(body, "shift_end"), "shift_end")
    if not (shift_end > shift_start):
        raise errors.invalid_request("shift_end must be strictly after shift_start.")

    with store.lock:
        util.lookup(store.stands, stand_id)
        # Half-open overlap vs non-CANCELLED shifts for the same worker (PRD §3.7).
        # [start, end) overlaps [s, e) iff start < e AND s < end.
        for sh in store.staff_shifts.values():
            if sh["worker_name"] != worker_name:
                continue
            if sh["status"] == "CANCELLED":
                continue
            if shift_start < sh["shift_end"] and sh["shift_start"] < shift_end:
                raise errors.shift_overlap()
        sh = {
            "stand_id": stand_id,
            "worker_name": worker_name,
            "shift_start": shift_start,
            "shift_end": shift_end,
            "status": "SCHEDULED",
        }
        util.stamp_create(sh)
        store.staff_shifts[sh["id"]] = sh
    return object_response(S.staff_shift(sh), 201)


@app.route("/concessions/staff-shifts/<sid>", methods=["GET"])
@require_auth([M, O])
def get_staff_shift(sid):
    sh = util.lookup(store.staff_shifts, sid)
    return object_response(S.staff_shift(sh))


@app.route("/concessions/stands/<sid>/staff-shifts", methods=["GET"])
@require_auth([M, O])
def list_stand_staff_shifts(sid):
    util.lookup(store.stands, sid)
    return list_response(store.staff_shifts.values(), S.staff_shift, lambda o: o["stand_id"] == sid)


@app.route("/concessions/staff-shifts/<sid>/check-in", methods=["POST"])
@require_auth([O])
def check_in_shift(sid):
    with store.lock:
        sh = util.lookup(store.staff_shifts, sid)
        if sh["status"] != "SCHEDULED":
            raise errors.invalid_state()
        sh["status"] = "CHECKED_IN"
        util.touch(sh)
        stand = store.stands[sh["stand_id"]]
        stand["assigned_staff_count"] += 1
        util.touch(stand)
    return object_response(S.staff_shift(sh))


@app.route("/concessions/staff-shifts/<sid>/check-out", methods=["POST"])
@require_auth([O])
def check_out_shift(sid):
    with store.lock:
        sh = util.lookup(store.staff_shifts, sid)
        if sh["status"] != "CHECKED_IN":
            raise errors.invalid_state()
        sh["status"] = "CHECKED_OUT"
        util.touch(sh)
        stand = store.stands[sh["stand_id"]]
        stand["assigned_staff_count"] -= 1
        util.touch(stand)
    return object_response(S.staff_shift(sh))


@app.route("/concessions/staff-shifts/<sid>/cancel", methods=["POST"])
@require_auth([M])
def cancel_shift(sid):
    with store.lock:
        sh = util.lookup(store.staff_shifts, sid)
        if sh["status"] != "SCHEDULED":
            raise errors.invalid_state()
        sh["status"] = "CANCELLED"
        util.touch(sh)
    return object_response(S.staff_shift(sh))


# ===========================================================================
# Test hook: clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@require_auth([M])
def set_clock():
    body = util.get_json_body()
    to_iso = util.require_field(body, "to_iso8601")
    dt = util.parse_datetime(to_iso, "to_iso8601")
    with store.lock:
        store.set_clock(dt)
    from db import _iso_millis
    return object_response({"current_utc": _iso_millis(dt)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
