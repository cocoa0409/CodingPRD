"""Order intake, lines, reads and the two status dimensions (PRD §3.3 - §3.4)."""
from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import ROLES, authenticate, require_owner
from common import fk_lookup, path_lookup
from errors import ApiError, fail
from store import D, lb

bp = Blueprint("orders", __name__)

DELIVERY_MODES = ("BULK", "BAGGED")
FULFILLMENT_STATES = ("NEW", "ALLOCATED", "ROUTED", "LOADED",
                      "DELIVERED", "SHORT_SHIPPED", "CANCELLED")
PRICING_STATES = ("UNPRICED", "PROVISIONAL", "FINAL", "INVOICED", "VOID")
ALLOCATION_STATES = ("UNALLOCATED", "RESERVED", "SHIPPED", "RELEASED")

ORDER_READ_ROLES = ("CustomerBuyer", "AccountManager", "PricingController",
                    "WarehouseOperator", "LogisticsPlanner", "TechnicalSpecialist",
                    "QualityManager", "PlatformAdmin")
ORDER_LIST_ROLES = ("CustomerBuyer", "AccountManager", "PricingController",
                    "WarehouseOperator", "LogisticsPlanner", "PlatformAdmin")
LINE_READ_ROLES = ORDER_READ_ROLES
SUMMARY_ROLES = ("CustomerBuyer", "AccountManager", "PricingController", "PlatformAdmin")


# ------------------------------------------------------------- intake ----
@bp.post("/orders")
def create_order():
    actor = authenticate(("CustomerBuyer",))
    body = v.body()
    customer_id = v.string(body, "customer_id", min_len=1)
    delivery_mode = v.enum(body, "delivery_mode", DELIVERY_MODES)
    requested_delivery_on = v.date(body, "requested_delivery_on")
    contract_id = v.string(body, "contract_id", required=False, default=None)
    fk_lookup("customers", customer_id)
    if contract_id is not None:
        fk_lookup("contracts", contract_id)
    require_owner(actor, customer_id)
    rec = store.base_record()
    rec.update({
        "customer_id": customer_id,
        "contract_id": contract_id,
        "delivery_mode": delivery_mode,
        "requested_delivery_on": requested_delivery_on,
        "fulfillment_status": "NEW",
        "pricing_status": "UNPRICED",
        "order_placed_on": None,
        "delivered_on": None,
        "subtotal_cents": 0,
        "fuel_surcharge_cents": 0,
        "tech_attach_fee_cents": 0,
        "volume_rebate_cents": 0,
        "total_cents": 0,
        "surge_window": False,
        "short_ship_lb": D("0.00"),
    })
    store.insert("orders", rec)
    return envelope.created(serialize.order(rec))


@bp.get("/orders/<oid>")
def read_order(oid):
    authenticate(ORDER_READ_ROLES)
    return envelope.ok(serialize.order(path_lookup("orders", oid)))


@bp.get("/orders")
def list_orders():
    authenticate(ORDER_LIST_ROLES)
    limit, offset = v.pagination()
    customer_id = v.q_str("customer_id")
    contract_id = v.q_str("contract_id")
    fulfillment = v.q_enum("fulfillment_status", FULFILLMENT_STATES)
    pricing = v.q_enum("pricing_status", PRICING_STATES)
    rows = [o for o in store.all_of("orders")
            if (customer_id is None or o["customer_id"] == customer_id)
            and (contract_id is None or o["contract_id"] == contract_id)
            and (fulfillment is None or o["fulfillment_status"] == fulfillment)
            and (pricing is None or o["pricing_status"] == pricing)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.order)
    return envelope.listing(data, limit, offset, total)


@bp.post("/orders/<oid>/lines")
def create_order_line(oid):
    actor = authenticate(("CustomerBuyer",))
    body = v.body()
    product_id = v.string(body, "product_id", min_len=1)
    quantity = v.number(body, "quantity_lb", exclusive_min=0)
    order = path_lookup("orders", oid)
    product = fk_lookup("products", product_id)
    require_owner(actor, order["customer_id"])
    if order["pricing_status"] != "UNPRICED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Lines may only be added while the order is UNPRICED")
    customer = store.get("customers", order["customer_id"])
    domain.check_allergen_program(customer, product)
    if order["delivery_mode"] == "BULK":
        if not product["bulk_capable"]:
            fail("ERR_PRODUCT_NOT_BULK_CAPABLE",
                 "A BULK order may only carry bulk-capable SKUs")
        if calc.find_silo(order["customer_id"], product_id) is None:
            fail("ERR_PRODUCT_NOT_BULK_CAPABLE",
                 "The bakery has no silo registered for this SKU")
    rec = store.base_record()
    rec.update({
        "order_id": order["id"],
        "product_id": product_id,
        "substituted_from_product_id": None,
        "lot_id": None,
        "silo_id": None,
        "quantity_lb": lb(quantity),
        "allocation_status": "UNALLOCATED",
        "unit_price_cents": 0,
        "extended_cents": 0,
        "contract_line_id": None,
    })
    store.insert("order_lines", rec)
    store.bump(order)
    return envelope.created(serialize.order_line(rec))


@bp.get("/orders/<oid>/lines")
def list_order_lines_of(oid):
    authenticate(LINE_READ_ROLES)
    limit, offset = v.pagination()
    order = path_lookup("orders", oid)
    rows = calc.order_lines_of(order["id"])
    data, total = v.page(rows, limit, offset, serialize.order_line)
    return envelope.listing(data, limit, offset, total)


@bp.get("/order-lines")
def list_order_lines():
    authenticate(LINE_READ_ROLES)
    limit, offset = v.pagination()
    filters = {
        "order_id": v.q_str("order_id"),
        "product_id": v.q_str("product_id"),
        "substituted_from_product_id": v.q_str("substituted_from_product_id"),
        "lot_id": v.q_str("lot_id"),
        "silo_id": v.q_str("silo_id"),
        "contract_line_id": v.q_str("contract_line_id"),
    }
    allocation_status = v.q_enum("allocation_status", ALLOCATION_STATES)
    rows = []
    for ln in store.all_of("order_lines"):
        if any(value is not None and ln[key] != value for key, value in filters.items()):
            continue
        if allocation_status is not None and ln["allocation_status"] != allocation_status:
            continue
        rows.append(ln)
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.order_line)
    return envelope.listing(data, limit, offset, total)


@bp.get("/order-lines/<lid>")
def read_order_line(lid):
    authenticate(LINE_READ_ROLES)
    return envelope.ok(serialize.order_line(path_lookup("order_lines", lid)))


# --------------------------------------------------- shared gate helpers ----
def _require_lines(order):
    lines = calc.order_lines_of(order["id"])
    if not lines:
        fail("ERR_INVALID_STATE_TRANSITION", "The order carries no lines")
    return lines


def _check_allergen_lines(order, customer):
    for ln in calc.order_lines_of(order["id"]):
        product = store.get("products", ln["product_id"])
        if product is not None:
            domain.check_allergen_program(customer, product)


def _check_contract_term(order, contract):
    if contract is None:
        return
    day = store.day_of(order["requested_delivery_on"])
    if not (store.day_of(contract["term_start_on"]) <= day
            <= store.day_of(contract["term_end_on"])):
        fail("ERR_CONTRACT_TERM_NOT_COVERING",
             "The requested delivery date falls outside the contract term")


def _check_contract_volume(order, per_line):
    pending = {}
    for item in per_line:
        cl_id = item["contract_line_id"]
        if cl_id is None:
            continue
        pending[cl_id] = pending.get(cl_id, D(0)) + D(item["line"]["quantity_lb"])
    for cl_id, extra in pending.items():
        cl = store.get("contract_lines", cl_id)
        if cl is None:
            continue
        if D(cl["volume_drawn_lb"]) + extra > D(cl["volume_committed_lb"]):
            fail("ERR_CONTRACT_VOLUME_EXCEEDED",
                 "The draw exceeds the committed volume on contract line %s" % cl_id)
    return pending


def _draw_contract_volume(pending):
    touched = {}
    for cl_id, extra in pending.items():
        cl = store.get("contract_lines", cl_id)
        if cl is None:
            continue
        cl["volume_drawn_lb"] = lb(D(cl["volume_drawn_lb"]) + extra)
        store.bump(cl)
        touched[cl["contract_id"]] = store.get("contracts", cl["contract_id"])
    for contract in touched.values():
        domain.evaluate_contract_volume(contract)


def _probe(order, **overrides):
    snapshot = dict(order)
    snapshot.update(overrides)
    return snapshot


# ------------------------------------------------------------ submission ----
@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    actor = authenticate(("CustomerBuyer",))
    v.body()
    order = path_lookup("orders", oid)
    require_owner(actor, order["customer_id"])
    if order["pricing_status"] != "UNPRICED" or order["fulfillment_status"] != "NEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an UNPRICED order in NEW may be submitted")
    _require_lines(order)
    customer = store.get("customers", order["customer_id"])
    if customer["status"] != "ACTIVE":
        fail("ERR_RELATED_ENTITY_STATE_INVALID", "The bakery account is not ACTIVE")
    contract = store.get("contracts", order["contract_id"]) if order["contract_id"] else None
    if contract is not None and contract["status"] != "ACTIVE":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "The referenced forward contract is not ACTIVE")
    _check_allergen_lines(order, customer)
    _check_contract_term(order, contract)
    placed_on = store.day_of(store.now())
    per_line, totals = calc.price_order(_probe(order, order_placed_on=placed_on),
                                        "provisional_order_date")
    pending = _check_contract_volume(order, per_line)
    if totals["total_cents"] < customer["min_drop_cents"]:
        fail("ERR_MIN_DROP_NOT_MET",
             "Order total %d is below the bakery minimum drop %d"
             % (totals["total_cents"], customer["min_drop_cents"]))
    if customer["open_exposure_cents"] + totals["total_cents"] > customer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "The order would push open exposure past the credit limit")
    order["order_placed_on"] = placed_on
    calc.apply_pricing(order, per_line, totals)
    order["pricing_status"] = "PROVISIONAL"
    store.bump(order)
    _draw_contract_volume(pending)
    calc.recompute_open_exposure(customer)
    return envelope.ok(serialize.order(order))


@bp.post("/orders/<oid>/reprice")
def reprice_order(oid):
    authenticate(("PricingController",))
    v.body()
    order = path_lookup("orders", oid)
    if order["pricing_status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a PROVISIONAL order may be repriced")
    if order["fulfillment_status"] in ("LOADED", "DELIVERED", "SHORT_SHIPPED", "CANCELLED"):
        fail("ERR_ORDER_DIMENSION_GATE",
             "Fulfillment status %s blocks repricing" % order["fulfillment_status"])
    per_line, totals = calc.price_order(order, "provisional_order_date")
    calc.apply_pricing(order, per_line, totals)
    store.bump(order)
    calc.recompute_open_exposure(store.get("customers", order["customer_id"]))
    return envelope.ok(serialize.order(order))


@bp.post("/orders/<oid>/finalize-pricing")
def finalize_pricing(oid):
    authenticate(("PricingController",))
    v.body()
    order = path_lookup("orders", oid)
    if order["pricing_status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a PROVISIONAL order may be finalized")
    if order["fulfillment_status"] not in ("DELIVERED", "SHORT_SHIPPED"):
        fail("ERR_ORDER_DIMENSION_GATE",
             "Pricing may only be finalized after the order is delivered")
    per_line, totals = calc.price_order(order, "final_delivery_date")
    calc.apply_pricing(order, per_line, totals)
    order["pricing_status"] = "FINAL"
    store.bump(order)
    calc.recompute_open_exposure(store.get("customers", order["customer_id"]))
    return envelope.ok(serialize.order(order))


@bp.post("/orders/<oid>/invoice")
def invoice_order(oid):
    actor = authenticate(("PricingController",))
    v.body()
    order = path_lookup("orders", oid)
    if order["pricing_status"] != "FINAL":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a FINAL order may be invoiced")
    if actor.user_id == order["customer_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The invoicing controller may not be the ordering bakery")
    for eng in store.all_of("engagements"):
        if eng["order_id"] == order["id"] and eng["status"] != "ATTACHED":
            fail("ERR_ENGAGEMENT_NOT_ATTACHED",
                 "Technical engagement %s is not ATTACHED" % eng["id"])
    order["pricing_status"] = "INVOICED"
    store.bump(order)
    calc.recompute_open_exposure(store.get("customers", order["customer_id"]))
    return envelope.ok(serialize.order(order))


# ------------------------------------------------------------ allocation ----
@bp.post("/orders/<oid>/allocate")
def allocate_order(oid):
    authenticate(("WarehouseOperator",))
    v.body()
    order = path_lookup("orders", oid)
    if order["fulfillment_status"] != "NEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an order in NEW may be allocated")
    if order["pricing_status"] not in ("PROVISIONAL", "FINAL"):
        fail("ERR_ORDER_DIMENSION_GATE",
             "An order must be priced before it can be allocated")
    lines = _require_lines(order)
    customer = store.get("customers", order["customer_id"])
    if customer["status"] != "ACTIVE":
        fail("ERR_RELATED_ENTITY_STATE_INVALID", "The bakery account is not ACTIVE")

    working = {}
    picks = []
    for ln in lines:
        lot = calc.select_lot(ln, on_hand_override=working)
        current = working.get(lot["id"])
        if current is None:
            current = D(lot["quantity_on_hand_lb"])
        working[lot["id"]] = current - D(ln["quantity_lb"])
        picks.append((ln, lot))

    silos = {}
    if order["delivery_mode"] == "BULK":
        for ln in lines:
            product = store.get("products", ln["product_id"])
            if not product["bulk_capable"]:
                fail("ERR_PRODUCT_NOT_BULK_CAPABLE",
                     "A BULK order may only carry bulk-capable SKUs")
        for ln in lines:
            silos[ln["id"]] = calc.bulk_fill_plan(order, ln)

    zones = {}
    for ln, lot in picks:
        qty = D(ln["quantity_lb"])
        lot["quantity_on_hand_lb"] = lb(D(lot["quantity_on_hand_lb"]) - qty)
        lot["quantity_reserved_lb"] = lb(D(lot["quantity_reserved_lb"]) + qty)
        store.bump(lot)
        ln["lot_id"] = lot["id"]
        silo = silos.get(ln["id"])
        ln["silo_id"] = silo["id"] if silo is not None else None
        ln["allocation_status"] = "RESERVED"
        store.bump(ln)
        zones[lot["zone_id"]] = store.get("zones", lot["zone_id"])
    for zone in zones.values():
        calc.recompute_zone_on_hand(zone)
    order["fulfillment_status"] = "ALLOCATED"
    store.bump(order)
    calc.recompute_risk_score(customer, "exposure_provisional")
    return envelope.ok(serialize.order(order))


@bp.post("/orders/<oid>/deallocate")
def deallocate_order(oid):
    authenticate(("WarehouseOperator",))
    v.body()
    order = path_lookup("orders", oid)
    if order["fulfillment_status"] != "ALLOCATED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an ALLOCATED order may be deallocated")
    for stop in store.all_of("stops"):
        if stop["order_id"] == order["id"] and stop["status"] == "PLANNED":
            fail("ERR_RELATED_ENTITY_STATE_INVALID",
                 "A planned route stop still references this order")
    domain.release_order_reservations(order)
    order["fulfillment_status"] = "NEW"
    store.bump(order)
    calc.recompute_risk_score(store.get("customers", order["customer_id"]),
                              "exposure_provisional")
    return envelope.ok(serialize.order(order))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    actor = authenticate(("CustomerBuyer",))
    body = v.body()
    v.string(body, "cancellation_reason", required=False, max_len=200)
    order = path_lookup("orders", oid)
    require_owner(actor, order["customer_id"])
    if order["fulfillment_status"] not in ("NEW", "ALLOCATED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An order in %s cannot be cancelled" % order["fulfillment_status"])
    domain.release_order_reservations(order)
    domain.return_contract_volume(order)
    order["fulfillment_status"] = "CANCELLED"
    order["pricing_status"] = "VOID"
    order["subtotal_cents"] = 0
    order["fuel_surcharge_cents"] = 0
    order["volume_rebate_cents"] = 0
    order["tech_attach_fee_cents"] = 0
    order["total_cents"] = 0
    store.bump(order)
    customer = store.get("customers", order["customer_id"])
    calc.recompute_open_exposure(customer)
    return envelope.ok(serialize.order(order))


@bp.get("/orders/<oid>/pricing-summary")
def pricing_summary(oid):
    authenticate(SUMMARY_ROLES)
    order = path_lookup("orders", oid)
    variant = ("final_delivery_date"
               if order["pricing_status"] in ("FINAL", "INVOICED")
               else "provisional_order_date")
    lines = calc.order_lines_of(order["id"])
    quotes = {}
    for ln in lines:
        try:
            _unit, _cl, quote = calc.settlement_price(order, ln, variant)
        except ApiError:
            quote = None
        quotes[ln["id"]] = quote
    return envelope.ok(serialize.pricing_summary(order, lines, quotes))
