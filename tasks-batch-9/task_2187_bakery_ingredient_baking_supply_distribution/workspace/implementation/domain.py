"""Shared state-machine mechanics and cascades (PRD §2.8, §2.10, §3.7)."""
import calc
import store
from errors import fail
from store import D, lb


# ---- allergen program compatibility (PRD §2.8) ---------------------------
def check_allergen_program(customer, product):
    klass = product["allergen_class"]
    program = customer["allergen_program"]
    if program == "GLUTEN_FREE_CERTIFIED" and klass == "GLUTEN":
        fail("ERR_ALLERGEN_PROGRAM_CONFLICT",
             "A GLUTEN_FREE_CERTIFIED bakery may not receive a GLUTEN product")
    if program == "NUT_FREE_CERTIFIED" and klass in ("TREE_NUT", "PEANUT"):
        fail("ERR_ALLERGEN_PROGRAM_CONFLICT",
             "A NUT_FREE_CERTIFIED bakery may not receive a %s product" % klass)
    if customer["risk_tier"] == "RED" and klass in ("TREE_NUT", "PEANUT"):
        fail("ERR_ALLERGEN_PROGRAM_CONFLICT",
             "A RED risk-tier bakery may not receive a %s product" % klass)


def order_allergen_classes(order):
    classes = set()
    for ln in calc.order_lines_of(order["id"]):
        product = store.get("products", ln["product_id"])
        if product is not None:
            classes.add(product["allergen_class"])
    return classes


# ---- contract auto-transitions (PRD §3.2) -------------------------------
def evaluate_contract_volume(contract):
    if contract is None:
        return
    lines = calc.contract_lines_of(contract["id"])
    calc.recompute_contract_volumes(contract)
    if not lines:
        store.bump(contract)
        return
    all_drawn = all(D(cl["volume_drawn_lb"]) >= D(cl["volume_committed_lb"]) for cl in lines)
    if contract["status"] == "ACTIVE" and all_drawn:
        contract["status"] = "EXHAUSTED"
    elif contract["status"] == "EXHAUSTED" and not all_drawn:
        if store.day_of(contract["term_end_on"]) >= store.clock_date():
            contract["status"] = "ACTIVE"
    store.bump(contract)


# ---- inventory release ---------------------------------------------------
def release_line_reservation(line, clear_refs=True, new_status="UNALLOCATED"):
    """Return the line's reserved pounds to the picked lot's on-hand bucket."""
    lot = store.get("lots", line["lot_id"])
    qty = D(line["quantity_lb"])
    if lot is not None and line["allocation_status"] == "RESERVED":
        lot["quantity_reserved_lb"] = lb(D(lot["quantity_reserved_lb"]) - qty)
        lot["quantity_on_hand_lb"] = lb(D(lot["quantity_on_hand_lb"]) + qty)
        store.bump(lot)
    line["allocation_status"] = new_status
    if clear_refs:
        line["lot_id"] = None
        line["silo_id"] = None
    store.bump(line)
    return lot


def release_order_reservations(order):
    """Compensating action shared by deallocate and cancel."""
    zones = {}
    for ln in calc.order_lines_of(order["id"]):
        lot = release_line_reservation(ln)
        if lot is not None:
            zones[lot["zone_id"]] = store.get("zones", lot["zone_id"])
    for zone in zones.values():
        calc.recompute_zone_on_hand(zone)


def return_contract_volume(order, pounds_by_line=None):
    """Reduce every contract line's drawn volume by the pounds this order drew."""
    touched = {}
    for ln in calc.order_lines_of(order["id"]):
        cl_id = ln["contract_line_id"]
        if cl_id is None:
            continue
        cl = store.get("contract_lines", cl_id)
        if cl is None:
            continue
        qty = D(ln["quantity_lb"]) if pounds_by_line is None else D(pounds_by_line.get(ln["id"], 0))
        if qty == 0:
            continue
        cl["volume_drawn_lb"] = lb(max(D(0), D(cl["volume_drawn_lb"]) - qty))
        store.bump(cl)
        touched[cl["contract_id"]] = store.get("contracts", cl["contract_id"])
    for contract in touched.values():
        evaluate_contract_volume(contract)


# ---- lot release cascade, hops 1-4 (PRD §3.7) ---------------------------
def lot_release_cascade(lot):
    affected_orders = []
    for ln in store.sort_created(store.all_of("order_lines")):
        if ln["lot_id"] != lot["id"] or ln["allocation_status"] != "RESERVED":
            continue
        # HOP 1
        qty = D(ln["quantity_lb"])
        lot["quantity_reserved_lb"] = lb(D(lot["quantity_reserved_lb"]) - qty)
        lot["quantity_on_hand_lb"] = lb(D(lot["quantity_on_hand_lb"]) + qty)
        ln["allocation_status"] = "UNALLOCATED"
        store.bump(ln)
        order = store.get("orders", ln["order_id"])
        if order is not None and order not in affected_orders:
            affected_orders.append(order)

    routes = {}
    for order in affected_orders:
        was_routed = order["fulfillment_status"] == "ROUTED"
        # HOP 2
        if order["fulfillment_status"] in ("ALLOCATED", "ROUTED"):
            order["fulfillment_status"] = "NEW"
            store.bump(order)
        if not was_routed:
            continue
        # HOP 3
        for stop in store.all_of("stops"):
            if stop["order_id"] != order["id"] or stop["status"] != "PLANNED":
                continue
            stop["status"] = "CANCELLED"
            store.bump(stop)
            routes[stop["route_id"]] = store.get("routes", stop["route_id"])

    for route in routes.values():
        if route is None:
            continue
        calc.apply_waterfall(route, enforce=False)
        store.bump(route)
        # HOP 4
        if route["stop_count"] == 0 and route["status"] == "SEALED":
            route["status"] = "PLANNING"
            route["allergen_class_lock"] = "NONE"
            for stop in calc.stops_of(route["id"]):
                if stop["sequence_no"] != 0:
                    stop["sequence_no"] = 0
                    store.bump(stop)
            store.bump(route)


# ---- route completion (PRD §3.10) ---------------------------------------
def maybe_complete_route(route):
    stops = [s for s in calc.stops_of(route["id"]) if s["status"] != "CANCELLED"]
    if any(s["status"] == "PLANNED" for s in stops):
        return
    if route["status"] != "DISPATCHED":
        return
    route["status"] = "COMPLETED"
    delivered = D(0)
    for stop in stops:
        delivered += D(stop.get("delivered_lb") or 0)
    route["stop_count"] = len(stops)
    route["planned_load_lb"] = lb(delivered)
    route["utilization_pct"] = store.round_half_up(
        delivered / D(route["vehicle_capacity_lb"]) * D(100), 2)
    store.bump(route)


def maybe_deplete_lot(lot):
    if lot is None or lot["status"] != "AVAILABLE":
        return
    if lb(lot["quantity_on_hand_lb"]) == 0 and lb(lot["quantity_reserved_lb"]) == 0:
        lot["status"] = "DEPLETED"
        store.bump(lot)
        calc.recompute_zone_on_hand(store.get("zones", lot["zone_id"]))


# ---- logical clock advance (PRD §2.4) ----------------------------------
def advance_clock(instant):
    store.set_now(instant)
    clock_day = store.clock_date()
    for contract in store.sort_created(store.all_of("contracts")):
        if contract["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        if clock_day > store.day_of(contract["term_end_on"]):
            contract["status"] = "EXPIRED"
            store.bump(contract)
    for zone in store.all_of("zones"):
        before = zone["status"]
        refresh_zone_status(zone)
        if zone["status"] != before:
            store.bump(zone)
    for lot in store.sort_created(store.all_of("lots")):
        if lot["status"] not in ("AVAILABLE", "QUARANTINED"):
            continue
        if clock_day >= store.day_of(lot["expires_on"]):
            lot_release_cascade(lot)
            lot["status"] = "EXPIRED"
            store.bump(lot)
            calc.recompute_zone_on_hand(store.get("zones", lot["zone_id"]))


# ---- zone lockout ------------------------------------------------------
def zone_in_lockout(zone):
    start = zone["lockout_start_at"]
    end = zone["lockout_end_at"]
    if start is None or end is None:
        return False
    return start <= store.now() <= end


def refresh_zone_status(zone):
    zone["status"] = "SANITATION_LOCKOUT" if zone_in_lockout(zone) else "OPEN"
