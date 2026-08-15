"""Purchase orders and order lines (PRD §3.4, §3.5, §3.7).

Two independent state dimensions on the order: fulfillment_status
(DRAFT -> CONFIRMED -> ALLOCATED -> SHIPPED -> DELIVERED, or CANCELLED) and
financial_status (UNBILLED -> INVOICED -> PARTIALLY_PAID -> PAID | CREDITED).
Allocation is the API's single OCC-guarded write (expected_order_version).
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from services import allocation as alloc_service
from services import events as event_service
from services import pricing as pricing_service
from validation import (get_body, req_str, req_int, req_enum, opt_bool,
                        body_fk, path_entity)

bp = Blueprint("orders", __name__)

SEGREGATION_MODES = ["STANDARD", "CONTROLLED", "COLD_CHAIN", "SEGREGATED_COMBINED"]
SEGREGATION_COVERAGE = {
    "STANDARD": set(),
    "CONTROLLED": {"CONTROLLED"},
    "COLD_CHAIN": {"COLD_CHAIN"},
    "SEGREGATED_COMBINED": {"CONTROLLED", "COLD_CHAIN"},
}


def _order(order_id):
    return path_entity(store.purchase_orders, order_id, "PurchaseOrder")


def _lines_of(order_id):
    return [l for l in store.order_lines.values() if l["order_id"] == order_id]


# --- order CRUD ------------------------------------------------------------

@bp.route("/wholesale/purchase-orders", methods=["POST"])
@endpoint(["OrderManager"])
def create_order():
    body = get_body()
    customer = body_fk(body, "customer_id", store.trading_partners, "TradingPartner")
    if customer["partner_kind"] != "CUSTOMER":
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "customer_id must reference a partner whose partner_kind is CUSTOMER")
    ship_to_state = req_str(body, "ship_to_state")
    is_340b = opt_bool(body, "is_340b_order", default=False)
    order = {
        "id": db.new_id(),
        "customer_id": customer["id"],
        "ship_to_state": ship_to_state,
        "fulfillment_status": "DRAFT",
        "financial_status": "UNBILLED",
        "invoice_total_cents": 0,
        "invoice_balance_cents": 0,
        "is_340b_order": is_340b,
        "_delivered_at": None,
    }
    db.new_common(order)
    store.purchase_orders[order["id"]] = order
    return created(order)


@bp.route("/wholesale/purchase-orders", methods=["GET"])
@endpoint(ALL_ROLES)
def list_orders():
    pg = Paginator()
    rows = list(store.purchase_orders.values())
    rows = pg.filter(rows, "customer_id")
    rows = pg.filter(rows, "fulfillment_status")
    rows = pg.filter(rows, "financial_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/purchase-orders/<orderId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_order(orderId):
    return ok(_order(orderId))


@bp.route("/wholesale/purchase-orders/<orderId>/lines", methods=["GET"])
@endpoint(ALL_ROLES)
def list_order_lines(orderId):
    order = _order(orderId)
    pg = Paginator()
    return ok(pg(_lines_of(order["id"])), rtype="array", pagination=pg)


@bp.route("/wholesale/order-lines", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lines_global():
    pg = Paginator()
    rows = list(store.order_lines.values())
    rows = pg.filter(rows, "order_id")
    rows = pg.filter(rows, "product_id")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/order-lines/<lineId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_line(lineId):
    line = path_entity(store.order_lines, lineId, "OrderLine")
    return ok(line)


@bp.route("/wholesale/purchase-orders/<orderId>/lines", methods=["POST"])
@endpoint(["OrderManager"])
def add_line(orderId):
    order = _order(orderId)
    body = get_body()
    product = body_fk(body, "product_id", store.products, "Product")
    quantity = req_int(body, "quantity_requested")
    if quantity <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "quantity_requested must be strictly positive")
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(errors.ERR_ORDER_NOT_DRAFT[0], errors.ERR_ORDER_NOT_DRAFT[1],
                       "Lines may only be added to a DRAFT order")
    line = {
        "id": db.new_id(),
        "order_id": order["id"],
        "product_id": product["id"],
        "quantity_requested": quantity,
        "quantity_allocated": 0,
        "unit_price_cents": None,
        "extended_price_cents": None,
        "line_status": "PENDING",
        "_alloc_policy_id": None,
    }
    db.new_common(line)
    store.order_lines[line["id"]] = line
    return created(line)


# --- confirm ---------------------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/confirm", methods=["POST"])
@endpoint(["OrderManager"])
def confirm_order(orderId):
    order = _order(orderId)
    get_body(required=False)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(errors.ERR_ORDER_NOT_DRAFT[0], errors.ERR_ORDER_NOT_DRAFT[1],
                       "Order must be DRAFT to confirm")
    lines = _lines_of(order["id"])
    if not lines:
        raise ApiError(errors.ERR_ORDER_EMPTY[0], errors.ERR_ORDER_EMPTY[1],
                       "Order has no lines at confirm time")

    # License verification — deliberately ahead of the credit check (PRD §3.4):
    # an ACTIVE license for ship_to_state with valid_to at or beyond the clock.
    customer = store.trading_partners[order["customer_id"]]
    now = db.logical_now()
    candidates = [l for l in store.partner_state_licenses.values()
                  if l["partner_id"] == customer["id"]
                  and l["state_code"] == order["ship_to_state"]
                  and l["license_status"] == "ACTIVE"
                  and l["valid_to"] >= now]
    if not candidates:
        raise ApiError(errors.ERR_LICENSE_VERIFICATION_FAILED[0],
                       errors.ERR_LICENSE_VERIFICATION_FAILED[1],
                       "No ACTIVE license for ship_to_state or license expired at confirm time")
    products = [store.products[l["product_id"]] for l in lines]
    if any(p["is_controlled"] for p in products):
        if not any(l["license_scope"] in ("RX_AND_CONTROLLED", "FULL") for l in candidates):
            raise ApiError(errors.ERR_CONTROLLED_LICENSE_REQUIRED[0],
                           errors.ERR_CONTROLLED_LICENSE_REQUIRED[1],
                           "Order contains controlled product but license scope lacks controlled authority")
    if any(p["is_cold_chain"] for p in products):
        if not any(l["license_scope"] in ("RX_AND_COLD_CHAIN", "FULL") for l in candidates):
            raise ApiError(errors.ERR_COLD_CHAIN_LICENSE_REQUIRED[0],
                           errors.ERR_COLD_CHAIN_LICENSE_REQUIRED[1],
                           "Order contains cold-chain product but license scope lacks cold-chain authority")

    # Provisional pricing (order_line_pricing, provisional variant): requested
    # quantities stand in because nothing has been allocated yet.
    provisional_total = 0
    for line, product in zip(lines, products):
        provisional_total += line["quantity_requested"] * pricing_service.unit_price_for(order, product)

    if customer["open_receivable_cents"] + provisional_total > customer["credit_limit_cents"]:
        raise ApiError(errors.ERR_CREDIT_LIMIT_EXCEEDED[0], errors.ERR_CREDIT_LIMIT_EXCEEDED[1],
                       "Projected open receivable would exceed the customer's credit limit")

    pricing_service.price_lines_provisional(order)
    order["fulfillment_status"] = "CONFIRMED"
    order["financial_status"] = "INVOICED"
    db.touch(order)
    customer["open_receivable_cents"] += order["invoice_total_cents"]
    db.touch(customer)
    return ok(order)


# --- allocate (OCC-guarded) -------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/allocate", methods=["POST"])
@endpoint(["OrderManager"])
def allocate_order(orderId):
    order = _order(orderId)
    body = get_body()
    expected = req_int(body, "expected_order_version")
    # OCC (priority 4.5): evaluated BEFORE state preconditions and all
    # business rules (PRD §2.7); nothing is mutated on a stale write.
    if expected != order["version"]:
        raise ApiError(errors.ERR_STALE_VERSION[0], errors.ERR_STALE_VERSION[1],
                       "expected_order_version does not match the order's current version")
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError(errors.ERR_ORDER_NOT_CONFIRMED[0], errors.ERR_ORDER_NOT_CONFIRMED[1],
                       "Order must be CONFIRMED for allocation")

    alloc_service.run_allocation(order)
    pricing_service.reprice_lines_final(order)
    lines = _lines_of(order["id"])
    if lines and all(l["line_status"] == "ALLOCATED" for l in lines):
        order["fulfillment_status"] = "ALLOCATED"
    db.touch(order)
    return ok(order)


# --- ship -------------------------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/ship", methods=["POST"])
@endpoint(["WarehouseOperator"])
def ship_order(orderId):
    order = _order(orderId)
    body = get_body()
    mode = req_enum(body, "segregation_mode", SEGREGATION_MODES)
    case_ids = body.get("case_ids")
    if case_ids is None:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "case_ids is required")
    if not isinstance(case_ids, list) or any(not isinstance(c, str) for c in case_ids):
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "case_ids must be a list of case id strings")
    cases = []
    for cid in case_ids:
        case = store.serialized_cases.get(cid)
        if case is None:
            raise ApiError(errors.ERR_REFERENCE_NOT_FOUND[0], errors.ERR_REFERENCE_NOT_FOUND[1],
                           "SerializedCase '%s' does not exist" % cid)
        cases.append(case)

    if order["fulfillment_status"] not in ("CONFIRMED", "ALLOCATED"):
        raise ApiError(errors.ERR_ORDER_NOT_SHIPPABLE[0], errors.ERR_ORDER_NOT_SHIPPABLE[1],
                       "Order must be CONFIRMED or ALLOCATED to ship")
    lines = _lines_of(order["id"])
    if any((l["quantity_allocated"] or 0) <= 0 for l in lines):
        raise ApiError(errors.ERR_LINES_UNALLOCATED[0], errors.ERR_LINES_UNALLOCATED[1],
                       "Every order line must have quantity_allocated > 0 before shipping")

    # Suspect-stock interdiction (priority 7): no listed case may be
    # QUARANTINED, and no OPEN or QUARANTINED investigation may exist for any
    # listed case — evaluated ahead of the case-state check so interdicted
    # stock surfaces the safety rejection (ERR_PRODUCT_UNDER_INVESTIGATION).
    open_investigation_case_ids = {
        inv["case_id"] for inv in store.suspect_investigations.values()
        if inv["investigation_status"] in ("OPEN", "QUARANTINED")
    }
    for case in cases:
        if case["case_status"] == "QUARANTINED" or case["id"] in open_investigation_case_ids:
            raise ApiError(errors.ERR_PRODUCT_UNDER_INVESTIGATION[0],
                           errors.ERR_PRODUCT_UNDER_INVESTIGATION[1],
                           "A listed case is quarantined or under a suspect investigation")

    if not cases:
        raise ApiError(errors.ERR_CASE_NOT_SHIPPABLE[0], errors.ERR_CASE_NOT_SHIPPABLE[1],
                       "case_ids must be non-empty")
    line_product_ids = {l["product_id"] for l in lines}
    for case in cases:
        if case["case_status"] != "COMMISSIONED" or case["product_id"] not in line_product_ids:
            raise ApiError(errors.ERR_CASE_NOT_SHIPPABLE[0], errors.ERR_CASE_NOT_SHIPPABLE[1],
                           "Every listed case must be COMMISSIONED with a product matching some line")

    now = db.logical_now()
    for case in cases:
        if not case["expiry_date"] > now:
            raise ApiError(errors.ERR_PRODUCT_EXPIRED[0], errors.ERR_PRODUCT_EXPIRED[1],
                           "Case expiry_date is not strictly after the current logical clock")

    needed = set()
    for line in lines:
        product = store.products[line["product_id"]]
        if product["is_controlled"]:
            needed.add("CONTROLLED")
        if product["is_cold_chain"]:
            needed.add("COLD_CHAIN")
    if not needed <= SEGREGATION_COVERAGE[mode]:
        raise ApiError(errors.ERR_SEGREGATION_REQUIRED[0], errors.ERR_SEGREGATION_REQUIRED[1],
                       "segregation_mode does not cover every line's segregation class")

    order["fulfillment_status"] = "SHIPPED"
    db.touch(order)
    seen = set()
    for case in cases:
        if case["id"] in seen:
            continue
        seen.add(case["id"])
        event_service.ship_case(case, order_id=order["id"])
    return ok(order)


# --- deliver ----------------------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/deliver", methods=["POST"])
@endpoint(["WarehouseOperator"])
def deliver_order(orderId):
    order = _order(orderId)
    get_body(required=False)
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError(errors.ERR_ORDER_NOT_SHIPPED[0], errors.ERR_ORDER_NOT_SHIPPED[1],
                       "Order must be SHIPPED to deliver")
    order["fulfillment_status"] = "DELIVERED"
    order["_delivered_at"] = db.logical_now()
    db.touch(order)
    return ok(order)


# --- cancel -----------------------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/cancel", methods=["POST"])
@endpoint(["OrderManager"])
def cancel_order(orderId):
    order = _order(orderId)
    get_body(required=False)
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError(errors.ERR_ORDER_NOT_CANCELLABLE[0], errors.ERR_ORDER_NOT_CANCELLABLE[1],
                       "Order must be DRAFT or CONFIRMED to cancel")
    was = order["fulfillment_status"]
    order["fulfillment_status"] = "CANCELLED"
    if was == "CONFIRMED" and order["financial_status"] == "INVOICED":
        order["financial_status"] = "CREDITED"
        customer = store.trading_partners.get(order["customer_id"])
        if customer is not None:
            customer["open_receivable_cents"] -= order["invoice_balance_cents"]
            db.touch(customer)
        order["invoice_balance_cents"] = 0
        alloc_service.release_order_allocations(order)
    db.touch(order)
    return ok(order)


# --- payments ---------------------------------------------------------------

@bp.route("/wholesale/purchase-orders/<orderId>/payments", methods=["POST"])
@endpoint(["BillingClerk"])
def post_payment(orderId):
    order = _order(orderId)
    body = get_body()
    amount = req_int(body, "amount_cents")
    if order["financial_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise ApiError(errors.ERR_INVOICE_NOT_OPEN[0], errors.ERR_INVOICE_NOT_OPEN[1],
                       "Payments only against INVOICED or PARTIALLY_PAID orders")
    if amount <= 0 or amount > order["invoice_balance_cents"]:
        raise ApiError(errors.ERR_PAYMENT_AMOUNT_INVALID[0], errors.ERR_PAYMENT_AMOUNT_INVALID[1],
                       "Payment must be > 0 and <= invoice_balance_cents")
    order["invoice_balance_cents"] -= amount
    order["financial_status"] = "PAID" if order["invoice_balance_cents"] == 0 else "PARTIALLY_PAID"
    db.touch(order)
    customer = store.trading_partners.get(order["customer_id"])
    if customer is not None:
        customer["open_receivable_cents"] -= amount
        db.touch(customer)
    return ok(order, status=201)
