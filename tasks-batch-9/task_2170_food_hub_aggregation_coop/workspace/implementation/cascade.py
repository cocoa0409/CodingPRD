"""Compensating cascades, staging, route auto-advance and the clock sweep."""

import domain
import pricing
from constants import TEMP_TOLERANCE_C, WRITE_OFF_GRACE_DAYS
from store import add_days, db, set_clock, sorted_records, touch


# ---------------------------------------------------------------------------
# shared reversal body (hops 3, 4 and 5)
# ---------------------------------------------------------------------------

def _unwind_reserved(product_ids):
    """Reverse every RESERVED allocation drawing on one of product_ids whose
    order sits in AGGREGATED or SCHEDULED, then re-grade lines and re-price
    orders from the surviving rows."""
    affected_lines = {}
    affected_orders = {}

    for alloc in sorted_records(list(db.allocations.values())):
        if alloc["status"] != "RESERVED":
            continue
        if alloc["product_id"] not in product_ids:
            continue
        order = domain.allocation_order(alloc)
        if order is None or order["fulfillment_status"] not in ("AGGREGATED", "SCHEDULED"):
            continue
        alloc["status"] = "REVERSED"
        touch(alloc)
        product = db.products.get(alloc["product_id"])
        if product is not None:
            product["quantity_committed"] = max(0, product["quantity_committed"] - alloc["quantity"])
            domain.recompute_product_available(product)
            touch(product)
        line = db.lines.get(alloc["order_line_id"])
        if line is not None:
            affected_lines[line["id"]] = line
        affected_orders[order["id"]] = order

    # hop: each affected demand line recomputes its allocated quantity
    for line in affected_lines.values():
        allocated = domain.line_quantity_allocated(line)
        line["quantity_allocated"] = allocated
        if allocated == 0:
            line["status"] = "PENDING"
        elif allocated < line["quantity_requested"]:
            line["status"] = "SHORT"
        touch(line)

    # hop: each affected order re-prices, and an order left with nothing
    # allocated returns to DRAFT and is detached from its route
    for order in affected_orders.values():
        pricing.run_rollup(order, "provisional")
        total_allocated = sum(domain.line_quantity_allocated(l)
                              for l in domain.order_lines(order["id"]))
        if total_allocated == 0:
            route_id = order.get("route_id")
            order["fulfillment_status"] = "DRAFT"
            order["route_id"] = None
            order["route_sequence_no"] = None
            order["planned_arrival_at"] = None
            order["service_minutes"] = None
            order["order_pallets"] = 0
            if route_id is not None:
                route = db.routes.get(route_id)
                if route is not None:
                    domain.refresh_route_counts(route)
                    touch(route)
        touch(order)

    return affected_orders


# ---------------------------------------------------------------------------
# producer suspension (five hops)
# ---------------------------------------------------------------------------

def suspend_producer(producer):
    """ACTIVE -> SUSPENDED with the full delist-and-unwind cascade.  The manual
    and the compliance-triggered trigger share this body verbatim."""
    producer["onboarding_status"] = "SUSPENDED"
    producer["suspension_count"] += 1
    touch(producer)

    for product in domain.producer_products(producer["id"]):
        if product["status"] == "LISTED":
            product["status"] = "DELISTED"
            product["quantity_offered"] = 0
            domain.recompute_product_available(product)
            touch(product)

    product_ids = set(p["id"] for p in domain.producer_products(producer["id"]))
    _unwind_reserved(product_ids)


def terminate_producer(producer, from_status):
    producer["onboarding_status"] = "TERMINATED"
    touch(producer)
    if from_status in ("ACTIVE", "SUSPENDED"):
        for product in domain.producer_products(producer["id"]):
            if product["status"] != "DELISTED" or product["quantity_offered"] != 0:
                product["status"] = "DELISTED"
                product["quantity_offered"] = 0
                domain.recompute_product_available(product)
                touch(product)


# ---------------------------------------------------------------------------
# dock no-show (four hops)
# ---------------------------------------------------------------------------

def no_show_unwind(appointment):
    product_ids = set(p["id"] for p in domain.producer_products(appointment["producer_id"]))
    _unwind_reserved(product_ids)


# ---------------------------------------------------------------------------
# staging and route auto-advance
# ---------------------------------------------------------------------------

def stage_allocations(appointment, slot):
    temp = appointment.get("recorded_temp_c")
    setpoint = slot["temp_setpoint_c"]
    for alloc in sorted_records(list(db.allocations.values())):
        if alloc["status"] != "RESERVED":
            continue
        product = db.products.get(alloc["product_id"])
        if product is None or product["producer_id"] != appointment["producer_id"]:
            continue
        order = domain.allocation_order(alloc)
        if order is None or order["fulfillment_status"] != "SCHEDULED":
            continue
        alloc["status"] = "STAGED"
        alloc["staged_temp_c"] = temp
        # strict '>': a reading exactly at setpoint + tolerance is within tolerance
        alloc["temp_excursion"] = bool(temp is not None and temp > setpoint + TEMP_TOLERANCE_C)
        touch(alloc)


def advance_loaded_routes():
    """A route with at least one stop and no RESERVED allocation on any of its
    orders advances PLANNED -> LOADED on its own."""
    for route in sorted_records(list(db.routes.values())):
        if route["status"] != "PLANNED":
            continue
        orders = domain.route_orders(route["id"])
        if len(orders) < 1:
            continue
        blocked = False
        for order in orders:
            for alloc in domain.order_allocations(order["id"]):
                if alloc["status"] == "RESERVED":
                    blocked = True
                    break
            if blocked:
                break
        if blocked:
            continue
        route["status"] = "LOADED"
        touch(route)


def advance_completed_route(route):
    if route is None or route["status"] != "DISPATCHED":
        return
    orders = domain.route_orders(route["id"])
    if not orders:
        return
    for order in orders:
        if order["fulfillment_status"] not in ("DELIVERED", "CLOSED"):
            return
    route["status"] = "COMPLETED"
    touch(route)


# ---------------------------------------------------------------------------
# settlement helpers
# ---------------------------------------------------------------------------

def close_fulfillment(order):
    """The money axis closes the physical axis, never the reverse."""
    if order["fulfillment_status"] == "DELIVERED":
        order["fulfillment_status"] = "CLOSED"
        for line in domain.order_lines(order["id"]):
            if line["status"] == "DELIVERED":
                line["status"] = "SETTLED"
                touch(line)


def credit_patronage(order):
    """Every producer owning a DELIVERED allocation is credited the gross
    producer_amount_cents — no deduction for shrink."""
    for alloc in domain.order_allocations(order["id"]):
        if alloc["status"] != "DELIVERED":
            continue
        producer = domain.allocation_producer(alloc)
        if producer is None:
            continue
        producer["patronage_volume_cents"] += alloc["producer_amount_cents"]
        touch(producer)


def write_off_order(order, balance):
    order["settlement_status"] = "WRITTEN_OFF"
    buyer = db.buyers.get(order["buyer_id"])
    if buyer is not None:
        buyer["outstanding_balance_cents"] -= balance
        touch(buyer)
    close_fulfillment(order)
    touch(order)


# ---------------------------------------------------------------------------
# the four-part clock sweep (PRD 2.5)
# ---------------------------------------------------------------------------

def set_clock_and_sweep(instant):
    previous = {}
    for producer in db.producers.values():
        previous[producer["id"]] = domain.compliance_ok(producer)

    set_clock(instant)

    # 1. verified documents whose expiry instant has been reached expire
    for doc in sorted_records(list(db.documents.values())):
        if doc["status"] == "VERIFIED" and doc["expires_on"] <= instant:
            doc["status"] = "EXPIRED"
            touch(doc)

    # 2. re-evaluate every producer's compliance; suspend those that just lost it
    for producer in sorted_records(list(db.producers.values())):
        was_ok = previous.get(producer["id"], False)
        now_ok = domain.compliance_ok(producer)
        if producer["onboarding_status"] == "ACTIVE" and was_ok and not now_ok:
            suspend_producer(producer)

    # 3. dock slots whose bookable window has ended are closed (derived status)
    for slot in db.dock_slots.values():
        domain.refresh_slot(slot)

    # 4. invoiced orders past due plus the grace period, still owing, are written off
    for order in sorted_records(list(db.orders.values())):
        if order["settlement_status"] not in ("INVOICED", "PARTIALLY_PAID"):
            continue
        due = order.get("invoice_due_date")
        if due is None:
            continue
        balance = (order["invoiced_total_cents"] - order["paid_total_cents"]
                   - order["credit_memo_cents"])
        if balance <= 0:
            continue
        if instant > add_days(due, WRITE_OFF_GRACE_DAYS):
            write_off_order(order, balance)
